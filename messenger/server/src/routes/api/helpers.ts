/** Shared helpers for the /api bot-API routers. */
import { Request } from 'express';
import multer from 'multer';
import path from 'path';
import fs from 'fs';
import crypto from 'crypto';
import { v4 as uuidv4 } from 'uuid';
import { queryOne } from '../../db/index.js';
import { getMessengerEnv, resolveMessengerPath } from '../../env.js';

export const UPLOADS_DIR = resolveMessengerPath(
  getMessengerEnv('MESSENGER_UPLOADS_DIR', ''),
  path.join(__dirname, '..', '..', '..', 'uploads'),
);
if (!fs.existsSync(UPLOADS_DIR)) {
  fs.mkdirSync(UPLOADS_DIR, { recursive: true });
}

const storage = multer.diskStorage({
  destination: (_req, _file, cb) => {
    const dateFolder = new Date().toISOString().slice(0, 10);
    const dir = path.join(UPLOADS_DIR, dateFolder);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }
    cb(null, dir);
  },
  filename: (_req, _file, cb) => {
    const ext = path.extname(_file.originalname);
    cb(null, `${uuidv4()}${ext}`);
  },
});

export const upload = multer({ storage });

/**
 * Resolve the sender from (in priority order):
 *   1. x-api-key header (attached by apiKeyAuth middleware)
 *   2. senderId in body or query (strict ID-based identity)
 *   3. senderName in body or query (globally unique)
 */
export function resolveSender(req: Request): any | null {
  if ((req as any).apiUser) return (req as any).apiUser;
  const { body, query } = req;
  const senderIdRaw = body.senderId ?? query.senderId;
  const senderName = body.senderName || query.senderName;
  if (senderIdRaw !== undefined && senderIdRaw !== null && String(senderIdRaw).trim() !== '') {
    const senderId = Number(senderIdRaw);
    if (Number.isInteger(senderId) && senderId > 0) {
      return queryOne('SELECT * FROM users WHERE id = ?', [senderId]);
    }
    return null;
  }
  if (senderName) return queryOne('SELECT * FROM users WHERE name = ?', [senderName]);
  return null;
}

/** Check that a user is a member of a room. */
export function isRoomMember(roomId: number | string, userId: number): boolean {
  return !!queryOne(
    'SELECT 1 FROM room_members WHERE room_id = ? AND user_id = ?',
    [roomId, userId],
  );
}

export function generateApiKey(): string {
  return 'huni_' + crypto.randomBytes(24).toString('hex');
}

export function decodeImageDataUrl(data: unknown): { buffer: Buffer; ext: string } | { error: string } {
  if (typeof data !== 'string' || data.trim() === '') {
    return { error: 'No image data' };
  }

  const match = data.match(/^data:image\/([a-zA-Z0-9.+-]+);base64,([A-Za-z0-9+/=\s]+)$/);
  if (!match) {
    return { error: 'data must be a base64 image data URL' };
  }

  const base64Data = match[2].replace(/\s/g, '');
  if (!base64Data) {
    return { error: 'No image data' };
  }

  const buffer = Buffer.from(base64Data, 'base64');
  if (buffer.length === 0) {
    return { error: 'Decoded image is empty' };
  }

  const subtype = match[1].toLowerCase();
  const extMap: Record<string, string> = { jpeg: 'jpg', 'svg+xml': 'svg' };
  const safeSubtype = extMap[subtype] ?? (subtype.replace(/[^a-z0-9]/g, '') || 'png');
  return { buffer, ext: `.${safeSubtype}` };
}
