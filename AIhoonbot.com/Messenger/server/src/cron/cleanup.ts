import cron from 'node-cron';
import { queryAll, run } from '../db/index.js';
import fs from 'fs';
import path from 'path';

const UPLOADS_DIR = path.join(__dirname, '..', '..', 'uploads');
const MAX_AGE_DAYS = 30;

function cleanupOldFiles() {
  console.log('[CRON] Running file cleanup...');

  const cutoffDate = new Date();
  cutoffDate.setDate(cutoffDate.getDate() - MAX_AGE_DAYS);
  const cutoffStr = cutoffDate.toISOString().replace('T', ' ').slice(0, 19);

  // Find old file/image messages
  const oldMessages = queryAll(`
    SELECT id, file_url FROM messages
    WHERE type IN ('file', 'image')
    AND file_url IS NOT NULL
    AND created_at < ?
    AND is_deleted = 0
  `, [cutoffStr]);

  let deleted = 0;

  for (const msg of oldMessages) {
    if (msg.file_url) {
      const filePath = path.join(UPLOADS_DIR, '..', msg.file_url);
      try {
        if (fs.existsSync(filePath)) {
          fs.unlinkSync(filePath);
          deleted++;
        }
      } catch (err) {
        console.error(`[CRON] Failed to delete file: ${filePath}`, err);
      }
    }

    run("UPDATE messages SET file_url = NULL, file_name = NULL, file_size = NULL, content = '파일이 만료되었습니다.', updated_at = datetime('now') WHERE id = ?", [msg.id]);
  }

  // Clean up empty date folders
  try {
    if (fs.existsSync(UPLOADS_DIR)) {
      const dirs = fs.readdirSync(UPLOADS_DIR);
      for (const dir of dirs) {
        const dirPath = path.join(UPLOADS_DIR, dir);
        if (fs.statSync(dirPath).isDirectory()) {
          const files = fs.readdirSync(dirPath);
          if (files.length === 0) {
            fs.rmdirSync(dirPath);
          }
        }
      }
    }
  } catch (err) {
    console.error('[CRON] Failed to cleanup empty directories', err);
  }

  console.log(`[CRON] Cleanup complete. Deleted ${deleted} files from ${oldMessages.length} expired messages.`);
}

export function startCleanupCron() {
  // Run daily at 3 AM
  cron.schedule('0 3 * * *', () => {
    cleanupOldFiles();
  });

  console.log('[CRON] File cleanup job scheduled (daily at 3 AM)');
}
