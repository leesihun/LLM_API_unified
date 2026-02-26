import { Router, Request, Response } from 'express';
import multer from 'multer';
import path from 'path';
import fs from 'fs';

const STORAGE_ROOT = path.join(__dirname, '..', '..', 'storage');

if (!fs.existsSync(STORAGE_ROOT)) {
  fs.mkdirSync(STORAGE_ROOT, { recursive: true });
}

function safePath(userPath: string): string | null {
  const cleaned = userPath.replace(/\\/g, '/').replace(/^\/+/, '');
  const normalized = path.normalize(cleaned || '.');
  const full = path.join(STORAGE_ROOT, normalized);

  if (!full.startsWith(STORAGE_ROOT)) return null;
  return full;
}

function toVirtualPath(fullPath: string): string {
  return '/' + path.relative(STORAGE_ROOT, fullPath).replace(/\\/g, '/');
}

function resolveNameConflict(dir: string, originalName: string): string {
  let name = originalName;
  let counter = 1;
  const ext = path.extname(originalName);
  const base = path.basename(originalName, ext);

  while (fs.existsSync(path.join(dir, name))) {
    name = `${base} (${counter})${ext}`;
    counter++;
  }
  return name;
}

function getFileIcon(name: string, isDirectory: boolean): string {
  if (isDirectory) return 'folder';

  const ext = path.extname(name).toLowerCase();
  const imageExts = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.bmp', '.ico'];
  const videoExts = ['.mp4', '.avi', '.mkv', '.mov', '.wmv', '.webm'];
  const audioExts = ['.mp3', '.wav', '.flac', '.ogg', '.aac', '.wma'];
  const docExts = ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.txt', '.rtf', '.csv'];
  const codeExts = ['.js', '.ts', '.py', '.java', '.c', '.cpp', '.html', '.css', '.json', '.xml', '.md'];
  const archiveExts = ['.zip', '.rar', '.7z', '.tar', '.gz', '.bz2'];

  if (imageExts.includes(ext)) return 'image';
  if (videoExts.includes(ext)) return 'video';
  if (audioExts.includes(ext)) return 'audio';
  if (docExts.includes(ext)) return 'document';
  if (codeExts.includes(ext)) return 'code';
  if (archiveExts.includes(ext)) return 'archive';
  return 'file';
}

function getDirSize(dirPath: string): number {
  let size = 0;
  const entries = fs.readdirSync(dirPath, { withFileTypes: true });
  for (const entry of entries) {
    const fullPath = path.join(dirPath, entry.name);
    if (entry.isDirectory()) {
      size += getDirSize(fullPath);
    } else {
      size += fs.statSync(fullPath).size;
    }
  }
  return size;
}

const fileUpload = multer({
  storage: multer.diskStorage({
    destination: (req, _file, cb) => {
      const userPath = (req.query.path as string) || '/';
      const fullPath = safePath(userPath);
      if (!fullPath) {
        cb(new Error('Invalid path'), '');
        return;
      }
      if (!fs.existsSync(fullPath)) {
        fs.mkdirSync(fullPath, { recursive: true });
      }
      cb(null, fullPath);
    },
    filename: (req, file, cb) => {
      const userPath = (req.query.path as string) || '/';
      const fullPath = safePath(userPath);
      if (!fullPath) {
        cb(new Error('Invalid path'), '');
        return;
      }
      const safeName = resolveNameConflict(fullPath, Buffer.from(file.originalname, 'latin1').toString('utf8'));
      cb(null, safeName);
    },
  }),
  limits: { fileSize: 500 * 1024 * 1024 },
});

const router = Router();

router.get('/list', (req: Request, res: Response) => {
  const dirPath = (req.query.path as string) || '/';
  const fullPath = safePath(dirPath);

  if (!fullPath) {
    res.status(400).json({ error: 'Invalid path.' });
    return;
  }

  if (!fs.existsSync(fullPath) || !fs.statSync(fullPath).isDirectory()) {
    res.status(404).json({ error: 'Directory not found.' });
    return;
  }

  const entries = fs.readdirSync(fullPath, { withFileTypes: true });
  const items = entries.map((entry) => {
    const itemPath = path.join(fullPath, entry.name);
    const stat = fs.statSync(itemPath);
    const isDir = entry.isDirectory();

    return {
      name: entry.name,
      isDirectory: isDir,
      size: isDir ? getDirSize(itemPath) : stat.size,
      modifiedAt: stat.mtime.toISOString(),
      icon: getFileIcon(entry.name, isDir),
    };
  });

  items.sort((a, b) => {
    if (a.isDirectory !== b.isDirectory) return a.isDirectory ? -1 : 1;
    return a.name.localeCompare(b.name);
  });

  res.json({ path: dirPath, items });
});

router.post('/mkdir', (req: Request, res: Response) => {
  const { path: dirPath, name } = req.body;

  if (!name || !name.trim()) {
    res.status(400).json({ error: 'Folder name is required.' });
    return;
  }

  const sanitizedName = name.trim().replace(/[<>:"/\\|?*]/g, '_');
  const parentPath = safePath(dirPath || '/');

  if (!parentPath) {
    res.status(400).json({ error: 'Invalid path.' });
    return;
  }

  const newDirPath = path.join(parentPath, sanitizedName);

  if (!newDirPath.startsWith(STORAGE_ROOT)) {
    res.status(400).json({ error: 'Invalid path.' });
    return;
  }

  if (fs.existsSync(newDirPath)) {
    res.status(409).json({ error: 'Folder already exists.' });
    return;
  }

  fs.mkdirSync(newDirPath, { recursive: true });
  res.json({ name: sanitizedName, path: toVirtualPath(newDirPath) });
});

router.post('/upload', fileUpload.array('files', 50), (req: Request, res: Response) => {
  const files = req.files as Express.Multer.File[];

  if (!files || files.length === 0) {
    res.status(400).json({ error: 'No files provided.' });
    return;
  }

  const uploaded = files.map((f) => ({
    name: f.filename,
    size: f.size,
    path: toVirtualPath(f.path),
  }));

  res.json({ files: uploaded });
});

router.get('/download', (req: Request, res: Response) => {
  const filePath = req.query.path as string;

  if (!filePath) {
    res.status(400).json({ error: 'Path is required.' });
    return;
  }

  const fullPath = safePath(filePath);

  if (!fullPath) {
    res.status(400).json({ error: 'Invalid path.' });
    return;
  }

  if (!fs.existsSync(fullPath) || fs.statSync(fullPath).isDirectory()) {
    res.status(404).json({ error: 'File not found.' });
    return;
  }

  const fileName = path.basename(fullPath);
  res.setHeader('Content-Disposition', `attachment; filename*=UTF-8''${encodeURIComponent(fileName)}`);
  res.sendFile(fullPath);
});

router.post('/delete', (req: Request, res: Response) => {
  const { path: targetPath } = req.body;

  if (!targetPath) {
    res.status(400).json({ error: 'Path is required.' });
    return;
  }

  const fullPath = safePath(targetPath);

  if (!fullPath) {
    res.status(400).json({ error: 'Invalid path.' });
    return;
  }

  if (fullPath === STORAGE_ROOT) {
    res.status(400).json({ error: 'Cannot delete root directory.' });
    return;
  }

  if (!fs.existsSync(fullPath)) {
    res.status(404).json({ error: 'File or folder not found.' });
    return;
  }

  const stat = fs.statSync(fullPath);
  if (stat.isDirectory()) {
    fs.rmSync(fullPath, { recursive: true, force: true });
  } else {
    fs.unlinkSync(fullPath);
  }

  res.json({ success: true });
});

router.post('/rename', (req: Request, res: Response) => {
  const { path: targetPath, newName } = req.body;

  if (!targetPath || !newName || !newName.trim()) {
    res.status(400).json({ error: 'Path and new name are required.' });
    return;
  }

  const fullPath = safePath(targetPath);

  if (!fullPath) {
    res.status(400).json({ error: 'Invalid path.' });
    return;
  }

  if (fullPath === STORAGE_ROOT) {
    res.status(400).json({ error: 'Cannot rename root directory.' });
    return;
  }

  if (!fs.existsSync(fullPath)) {
    res.status(404).json({ error: 'File or folder not found.' });
    return;
  }

  const sanitizedName = newName.trim().replace(/[<>:"/\\|?*]/g, '_');
  const dir = path.dirname(fullPath);
  const newPath = path.join(dir, sanitizedName);

  if (!newPath.startsWith(STORAGE_ROOT)) {
    res.status(400).json({ error: 'Invalid name.' });
    return;
  }

  if (fs.existsSync(newPath)) {
    res.status(409).json({ error: 'A file or folder with that name already exists.' });
    return;
  }

  fs.renameSync(fullPath, newPath);
  res.json({ name: sanitizedName, path: toVirtualPath(newPath) });
});

export default router;
