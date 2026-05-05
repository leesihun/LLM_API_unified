import { Router, Request, Response } from 'express';
import { queryAll, queryOne, run } from '../db/index.js';

const router = Router();

// POST /auth/login - name-based login/register (ID is the primary identity)
router.post('/login', (req: Request, res: Response) => {
  const { name } = req.body;
  const ip = req.ip || req.socket.remoteAddress || 'unknown';
  const cleanIp = ip.replace('::ffff:', '');

  if (!name || typeof name !== 'string' || name.trim().length === 0) {
    res.status(400).json({ error: '이름을 입력해주세요.' });
    return;
  }

  const trimmedName = name.trim();

  if (trimmedName.length > 20) {
    res.status(400).json({ error: '이름은 20자 이하로 입력해주세요.' });
    return;
  }

  // Look up existing user by name
  let user = queryOne('SELECT * FROM users WHERE name = ?', [trimmedName]);

  if (user) {
    if (user.is_bot) {
      res.status(403).json({ error: '이 이름은 봇 계정입니다. 다른 이름으로 로그인해주세요.' });
      return;
    }
    // Update IP if changed (user may connect from a different machine)
    if (user.ip !== cleanIp) {
      run("UPDATE users SET ip = ?, updated_at = datetime('now') WHERE id = ?", [cleanIp, user.id]);
      user.ip = cleanIp;
    }
  } else {
    // Create new user
    const result = run('INSERT INTO users (ip, name) VALUES (?, ?)', [cleanIp, trimmedName]);
    user = queryOne('SELECT * FROM users WHERE id = ?', [result.lastInsertRowid]);
    if (!user) {
      res.status(500).json({ error: 'Failed to create user' });
      return;
    }
  }

  res.json({
    user: {
      id: user.id,
      ip: user.ip,
      name: user.name,
      isBot: !!user.is_bot,
      createdAt: user.created_at,
      updatedAt: user.updated_at,
    },
  });
});

// GET /auth/users - 모든 사용자 목록
router.get('/users', (_req: Request, res: Response) => {
  const users = queryAll('SELECT * FROM users ORDER BY name');
  res.json(
    users.map((u: any) => ({
      id: u.id,
      ip: u.ip,
      name: u.name,
      isBot: !!u.is_bot,
      createdAt: u.created_at,
      updatedAt: u.updated_at,
    }))
  );
});

// GET /auth/check - ID로 기존 사용자 확인
router.get('/check', (req: Request, res: Response) => {
  const userIdParam = (req.query.userId as string | undefined)?.trim();
  const userId = Number(userIdParam);
  if (!userIdParam || !Number.isInteger(userId) || userId <= 0) {
    res.json({ user: null });
    return;
  }
  const user = queryOne('SELECT * FROM users WHERE id = ?', [userId]);

  if (user && !user.is_bot) {
    res.json({
      user: {
        id: user.id,
        ip: user.ip,
        name: user.name,
        isBot: !!user.is_bot,
        createdAt: user.created_at,
        updatedAt: user.updated_at,
      },
    });
  } else {
    res.json({ user: null });
  }
});

export default router;
