import crypto from 'crypto';
import { queryAll } from '../db/index.js';

export type WebhookEvent =
  | 'new_message'
  | 'message_edited'
  | 'message_deleted'
  | 'message_read';

/**
 * Fire-and-forget delivery of webhook payloads to all matching subscribers.
 * Matching = active webhook whose `events` list includes `event`
 *            AND whose `room_id` is NULL (all rooms) or equals `roomId`.
 */
export async function dispatchWebhooks(
  event: WebhookEvent,
  roomId: number,
  payload: any,
) {
  const webhooks = queryAll(
    'SELECT * FROM webhooks WHERE is_active = 1 AND (room_id IS NULL OR room_id = ?)',
    [roomId],
  );

  for (const wh of webhooks) {
    const events: string[] = JSON.parse(wh.events || '[]');
    if (!events.includes(event)) continue;

    const body = JSON.stringify({
      event,
      roomId,
      timestamp: new Date().toISOString(),
      data: payload,
    });

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };

    if (wh.secret) {
      headers['x-webhook-signature'] = crypto
        .createHmac('sha256', wh.secret)
        .update(body)
        .digest('hex');
    }

    fetch(wh.url, {
      method: 'POST',
      headers,
      body,
      signal: AbortSignal.timeout(10_000),
    }).catch((err: any) =>
      console.error(`[Webhook] Delivery to ${wh.url} failed: ${err.message}`),
    );
  }
}
