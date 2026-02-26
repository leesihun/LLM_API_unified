import initSqlJs, { Database as SqlJsDatabase } from 'sql.js';
import path from 'path';
import fs from 'fs';

const DATA_DIR = path.join(__dirname, '..', '..', 'data');
const DB_PATH = path.join(DATA_DIR, 'messenger.db');

let db: SqlJsDatabase;

// Auto-save interval
let saveInterval: ReturnType<typeof setInterval> | null = null;

function saveDatabase() {
  if (!db) return;
  try {
    const data = db.export();
    const buffer = Buffer.from(data);
    fs.writeFileSync(DB_PATH, buffer);
  } catch (err) {
    console.error('Failed to save database:', err);
  }
}

export async function initDatabase(): Promise<SqlJsDatabase> {
  if (db) return db;

  if (!fs.existsSync(DATA_DIR)) {
    fs.mkdirSync(DATA_DIR, { recursive: true });
  }

  const SQL = await initSqlJs();

  // Load existing DB or create new one
  if (fs.existsSync(DB_PATH)) {
    const fileBuffer = fs.readFileSync(DB_PATH);
    db = new SQL.Database(fileBuffer);
  } else {
    db = new SQL.Database();
  }

  // Enable foreign keys
  db.run('PRAGMA foreign_keys = ON');

  // Create tables
  db.run(`
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ip TEXT NOT NULL,
      name TEXT NOT NULL UNIQUE,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
  `);

  db.run(`
    CREATE TABLE IF NOT EXISTS rooms (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      is_group INTEGER NOT NULL DEFAULT 0,
      created_by INTEGER NOT NULL,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      FOREIGN KEY (created_by) REFERENCES users(id)
    )
  `);

  db.run(`
    CREATE TABLE IF NOT EXISTS room_members (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      room_id INTEGER NOT NULL,
      user_id INTEGER NOT NULL,
      joined_at TEXT NOT NULL DEFAULT (datetime('now')),
      FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE,
      FOREIGN KEY (user_id) REFERENCES users(id),
      UNIQUE(room_id, user_id)
    )
  `);

  db.run(`
    CREATE TABLE IF NOT EXISTS messages (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      room_id INTEGER NOT NULL,
      sender_id INTEGER NOT NULL,
      content TEXT NOT NULL DEFAULT '',
      type TEXT NOT NULL DEFAULT 'text' CHECK(type IN ('text', 'image', 'file')),
      file_url TEXT,
      file_name TEXT,
      file_size INTEGER,
      is_edited INTEGER NOT NULL DEFAULT 0,
      is_deleted INTEGER NOT NULL DEFAULT 0,
      mentions TEXT NOT NULL DEFAULT '[]',
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      updated_at TEXT NOT NULL DEFAULT (datetime('now')),
      FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE,
      FOREIGN KEY (sender_id) REFERENCES users(id)
    )
  `);

  db.run(`
    CREATE TABLE IF NOT EXISTS read_receipts (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      message_id INTEGER NOT NULL,
      user_id INTEGER NOT NULL,
      read_at TEXT NOT NULL DEFAULT (datetime('now')),
      FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
      FOREIGN KEY (user_id) REFERENCES users(id),
      UNIQUE(message_id, user_id)
    )
  `);

  // Create indexes
  db.run('CREATE INDEX IF NOT EXISTS idx_messages_room_id ON messages(room_id)');
  db.run('CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at)');
  db.run('CREATE INDEX IF NOT EXISTS idx_room_members_room_id ON room_members(room_id)');
  db.run('CREATE INDEX IF NOT EXISTS idx_room_members_user_id ON room_members(user_id)');
  db.run('CREATE INDEX IF NOT EXISTS idx_read_receipts_message_id ON read_receipts(message_id)');
  db.run('CREATE INDEX IF NOT EXISTS idx_users_ip ON users(ip)');

  // --- Migrations for existing tables ---
  try { db.run('ALTER TABLE users ADD COLUMN is_bot INTEGER NOT NULL DEFAULT 0'); } catch (_) { /* column exists */ }

  // Migration: Change user identity from ip-only to name-based (allow multiple users per IP)
  try {
    const tableInfo = db.exec("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'");
    const createSql = tableInfo[0]?.values[0]?.[0] as string || '';
    if (createSql.includes('ip TEXT NOT NULL UNIQUE')) {
      db.run('PRAGMA foreign_keys = OFF');
      db.run(`CREATE TABLE users_new (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ip TEXT NOT NULL,
        name TEXT NOT NULL UNIQUE,
        is_bot INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
      )`);
      db.run(`INSERT INTO users_new (id, ip, name, is_bot, created_at, updated_at)
              SELECT id, ip, name, is_bot, created_at, updated_at FROM users`);
      db.run('DROP TABLE users');
      db.run('ALTER TABLE users_new RENAME TO users');
      db.run('CREATE INDEX IF NOT EXISTS idx_users_ip ON users(ip)');
      db.run('PRAGMA foreign_keys = ON');
      console.log('Migration: users table updated (ip no longer unique, name is now unique)');
    }
  } catch (err) {
    console.error('Migration failed (users table):', err);
  }

  // API keys for bot/agent authentication
  db.run(`
    CREATE TABLE IF NOT EXISTS api_keys (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      key TEXT NOT NULL UNIQUE,
      label TEXT NOT NULL DEFAULT '',
      is_active INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      last_used_at TEXT,
      FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )
  `);

  // Webhooks for push notifications to external services
  db.run(`
    CREATE TABLE IF NOT EXISTS webhooks (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      url TEXT NOT NULL,
      room_id INTEGER,
      events TEXT NOT NULL DEFAULT '["new_message"]',
      secret TEXT,
      is_active INTEGER NOT NULL DEFAULT 1,
      created_by INTEGER NOT NULL,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE,
      FOREIGN KEY (created_by) REFERENCES users(id)
    )
  `);

  // Web watchers for polling external URLs on an interval
  db.run(`
    CREATE TABLE IF NOT EXISTS web_watchers (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      url TEXT NOT NULL,
      room_id INTEGER NOT NULL,
      sender_id INTEGER NOT NULL,
      interval_seconds INTEGER NOT NULL DEFAULT 10,
      last_content TEXT,
      last_hash TEXT,
      is_active INTEGER NOT NULL DEFAULT 1,
      last_checked_at TEXT,
      last_changed_at TEXT,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE,
      FOREIGN KEY (sender_id) REFERENCES users(id)
    )
  `);

  db.run('CREATE INDEX IF NOT EXISTS idx_api_keys_key ON api_keys(key)');
  db.run('CREATE INDEX IF NOT EXISTS idx_api_keys_user_id ON api_keys(user_id)');
  db.run('CREATE INDEX IF NOT EXISTS idx_webhooks_room_id ON webhooks(room_id)');
  db.run('CREATE INDEX IF NOT EXISTS idx_web_watchers_is_active ON web_watchers(is_active)');

  // Message reactions
  db.run(`
    CREATE TABLE IF NOT EXISTS message_reactions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      message_id INTEGER NOT NULL,
      user_id INTEGER NOT NULL,
      emoji TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
      FOREIGN KEY (user_id) REFERENCES users(id),
      UNIQUE(message_id, user_id, emoji)
    )
  `);
  db.run('CREATE INDEX IF NOT EXISTS idx_reactions_message_id ON message_reactions(message_id)');

  // Pinned messages
  db.run(`
    CREATE TABLE IF NOT EXISTS pinned_messages (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      message_id INTEGER NOT NULL,
      room_id INTEGER NOT NULL,
      pinned_by INTEGER NOT NULL,
      pinned_at TEXT NOT NULL DEFAULT (datetime('now')),
      FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
      FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE,
      FOREIGN KEY (pinned_by) REFERENCES users(id),
      UNIQUE(message_id)
    )
  `);
  db.run('CREATE INDEX IF NOT EXISTS idx_pinned_room_id ON pinned_messages(room_id)');

  // reply_to column on messages
  try { db.run('ALTER TABLE messages ADD COLUMN reply_to INTEGER REFERENCES messages(id)'); } catch (_) { /* column exists */ }

  // Save to file
  saveDatabase();

  // Auto-save every 5 seconds
  if (saveInterval) clearInterval(saveInterval);
  saveInterval = setInterval(saveDatabase, 5000);

  // Save on process exit
  process.on('exit', saveDatabase);
  process.on('SIGINT', () => { saveDatabase(); process.exit(); });
  process.on('SIGTERM', () => { saveDatabase(); process.exit(); });

  console.log(`Database initialized at ${DB_PATH}`);
  return db;
}

export function getDb(): SqlJsDatabase {
  if (!db) throw new Error('Database not initialized. Call initDatabase() first.');
  return db;
}

export { saveDatabase };
