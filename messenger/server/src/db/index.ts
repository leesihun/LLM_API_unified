import { getDb, saveDatabase } from './init.js';
import type { Database as SqlJsDatabase } from 'sql.js';

// Helper functions to make sql.js feel more like better-sqlite3

/** Run a query and return all rows as objects */
export function queryAll(sql: string, params: any[] = []): any[] {
  const db = getDb();
  const stmt = db.prepare(sql);
  stmt.bind(params);
  const results: any[] = [];
  while (stmt.step()) {
    results.push(stmt.getAsObject());
  }
  stmt.free();
  return results;
}

/** Run a query and return the first row as an object, or null */
export function queryOne(sql: string, params: any[] = []): any | null {
  const db = getDb();
  const stmt = db.prepare(sql);
  stmt.bind(params);
  let result = null;
  if (stmt.step()) {
    result = stmt.getAsObject();
  }
  stmt.free();
  return result;
}

/** Run a statement (INSERT/UPDATE/DELETE) and return lastInsertRowid */
export function run(sql: string, params: any[] = []): { lastInsertRowid: number; changes: number } {
  const db = getDb();
  db.run(sql, params);

  const lastId = (db.exec("SELECT last_insert_rowid() as id")[0]?.values[0]?.[0] as number) || 0;
  const changes = db.getRowsModified();

  return { lastInsertRowid: lastId, changes };
}

/** Save database to disk */
export function save() {
  saveDatabase();
}

export { getDb };
