import crypto from 'crypto';
import { queryAll, queryOne, run } from '../db/index.js';
import { createMessage } from './messages.js';

const timers = new Map<number, ReturnType<typeof setInterval>>();

async function poll(watcherId: number) {
  const watcher = queryOne(
    'SELECT * FROM web_watchers WHERE id = ? AND is_active = 1',
    [watcherId],
  );
  if (!watcher) {
    stopWatcher(watcherId);
    return;
  }

  try {
    const response = await fetch(watcher.url);
    const content = await response.text();
    const hash = crypto.createHash('md5').update(content).digest('hex');

    run("UPDATE web_watchers SET last_checked_at = datetime('now') WHERE id = ?", [watcherId]);

    if (hash === watcher.last_hash) return;

    // Content changed — persist and send a message
    run(
      "UPDATE web_watchers SET last_content = ?, last_hash = ?, last_changed_at = datetime('now') WHERE id = ?",
      [content, hash, watcherId],
    );

    const truncated =
      content.length > 4000
        ? content.substring(0, 4000) + '\n...(truncated)'
        : content;
    const messageContent = `[Web Watcher] Content updated at ${watcher.url}\n\n${truncated}`;

    createMessage({
      roomId: watcher.room_id,
      senderId: watcher.sender_id,
      content: messageContent,
    });
  } catch (err: any) {
    console.error(`[WebPoller] Error fetching ${watcher.url}: ${err.message}`);
  }
}

export function startWatcher(watcherId: number, intervalSeconds: number) {
  if (timers.has(watcherId)) return;
  const timer = setInterval(() => poll(watcherId), intervalSeconds * 1000);
  timers.set(watcherId, timer);
  poll(watcherId); // immediate first poll
}

export function stopWatcher(watcherId: number) {
  const timer = timers.get(watcherId);
  if (timer) {
    clearInterval(timer);
    timers.delete(watcherId);
  }
}

export function startAllWatchers() {
  const watchers = queryAll(
    'SELECT id, interval_seconds FROM web_watchers WHERE is_active = 1',
  );
  for (const w of watchers) {
    startWatcher(w.id, w.interval_seconds);
  }
  if (watchers.length > 0) {
    console.log(`[WebPoller] Started ${watchers.length} active watcher(s)`);
  }
}

