import { Router, Request, Response } from 'express';
import multer from 'multer';
import path from 'path';
import fs from 'fs';
import { v4 as uuidv4 } from 'uuid';

const UPLOADS_DIR = process.env.MESSENGER_UPLOADS_DIR || path.join(__dirname, '..', '..', 'uploads');
const CHUNKS_DIR = process.env.MESSENGER_CHUNKS_DIR || path.join(__dirname, '..', '..', 'chunks');

if (!fs.existsSync(UPLOADS_DIR)) {
  fs.mkdirSync(UPLOADS_DIR, { recursive: true });
}
if (!fs.existsSync(CHUNKS_DIR)) {
  fs.mkdirSync(CHUNKS_DIR, { recursive: true });
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
  filename: (_req, file, cb) => {
    const ext = path.extname(file.originalname);
    cb(null, `${uuidv4()}${ext}`);
  },
});

// No limits — unlimited file size
const upload = multer({ storage });

// Chunk storage: temp dir first, moved after multer parses body fields
const chunkTempStorage = multer.diskStorage({
  destination: (_req, _file, cb) => {
    const tempDir = path.join(CHUNKS_DIR, '_temp');
    if (!fs.existsSync(tempDir)) fs.mkdirSync(tempDir, { recursive: true });
    cb(null, tempDir);
  },
  filename: (_req, _file, cb) => {
    cb(null, uuidv4());
  },
});
const uploadChunk = multer({ storage: chunkTempStorage });

const router = Router();

// POST /upload/file
router.post('/file', (req: Request, res: Response) => {
  console.log('[Upload /file] route reached — starting multer');
  // Wrap multer so its errors surface as JSON (not Express's default HTML 500)
  upload.single('file')(req, res, (err: any) => {
    console.log('[Upload /file] multer callback fired, err:', err?.message ?? 'none', 'file:', req.file?.originalname ?? 'none');
    if (err) {
      console.error('[Upload /file] multer error:', err.message, err.code);
      res.status(500).json({ error: err.message || 'Upload error', code: err.code });
      return;
    }

    if (!req.file) {
      console.warn('[Upload /file] No file received in request');
      res.status(400).json({ error: 'No file received' });
      return;
    }

    const dateFolder = new Date().toISOString().slice(0, 10);
    const fileUrl = `/uploads/${dateFolder}/${req.file.filename}`;
    const fileName =
      req.body.fileName ||
      Buffer.from(req.file.originalname, 'latin1').toString('utf8');

    console.log(
      `[Upload /file] OK  ${fileName}  ${(req.file.size / 1024 / 1024).toFixed(2)} MB  -> ${fileUrl}`
    );

    res.json({ fileUrl, fileName, fileSize: req.file.size });
  });
});

// POST /upload/file-chunk  — chunked upload to bypass Cloudflare 100 MB limit
// Client sends chunks sequentially; server assembles when all chunks arrive.
router.post('/file-chunk', (req: Request, res: Response) => {
  uploadChunk.single('chunk')(req, res, (err: any) => {
    if (err) {
      console.error('[Upload /file-chunk] multer error:', err.message);
      res.status(500).json({ error: err.message || 'Chunk upload error' });
      return;
    }
    if (!req.file) {
      res.status(400).json({ error: 'No chunk received' });
      return;
    }

    const { uploadId, chunkIndex, totalChunks, fileName } = req.body;
    const idx = parseInt(chunkIndex, 10);
    const total = parseInt(totalChunks, 10);

    if (!uploadId || isNaN(idx) || isNaN(total) || total < 1) {
      fs.unlinkSync(req.file.path);
      res.status(400).json({ error: 'Missing or invalid chunk metadata' });
      return;
    }

    // Move temp file to per-upload chunk directory
    const chunkDir = path.join(CHUNKS_DIR, uploadId);
    if (!fs.existsSync(chunkDir)) fs.mkdirSync(chunkDir, { recursive: true });
    const chunkPath = path.join(chunkDir, `chunk_${String(idx).padStart(6, '0')}`);
    fs.renameSync(req.file.path, chunkPath);

    const received = fs.readdirSync(chunkDir).length;
    console.log(`[Upload /file-chunk] ${uploadId} chunk ${idx + 1}/${total} received (${received} total)`);

    if (received < total) {
      res.json({ done: false, received, total });
      return;
    }

    // All chunks received — assemble into final file
    const safeFileName = Buffer.from(fileName || 'file', 'latin1').toString('utf8');
    const ext = path.extname(safeFileName);
    const dateFolder = new Date().toISOString().slice(0, 10);
    const dir = path.join(UPLOADS_DIR, dateFolder);
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });

    const finalName = `${uuidv4()}${ext}`;
    const finalPath = path.join(dir, finalName);
    const writeStream = fs.createWriteStream(finalPath);
    const sortedChunks = fs.readdirSync(chunkDir).sort();

    for (const chunk of sortedChunks) {
      writeStream.write(fs.readFileSync(path.join(chunkDir, chunk)));
    }
    writeStream.end();

    writeStream.on('finish', () => {
      try { fs.rmSync(chunkDir, { recursive: true, force: true }); } catch {}
      const fileUrl = `/uploads/${dateFolder}/${finalName}`;
      const fileSize = fs.statSync(finalPath).size;
      console.log(`[Upload /file-chunk] Assembled ${safeFileName} (${total} chunks, ${(fileSize / 1024 / 1024).toFixed(2)} MB) -> ${fileUrl}`);
      res.json({ done: true, fileUrl, fileName: safeFileName, fileSize });
    });

    writeStream.on('error', (writeErr: Error) => {
      console.error('[Upload /file-chunk] Assembly error:', writeErr);
      try { fs.rmSync(chunkDir, { recursive: true, force: true }); } catch {}
      if (!res.headersSent) res.status(500).json({ error: 'File assembly failed' });
    });
  });
});

// POST /upload/image-base64
router.post('/image-base64', (req: Request, res: Response) => {
  const { data, fileName } = req.body;

  if (!data) {
    res.status(400).json({ error: 'No image data' });
    return;
  }

  const base64Data = data.replace(/^data:image\/\w+;base64,/, '');
  const buffer = Buffer.from(base64Data, 'base64');

  let ext = '.png';
  const mimeMatch = data.match(/^data:image\/(\w+);base64,/);
  if (mimeMatch) ext = '.' + mimeMatch[1].replace('jpeg', 'jpg');

  const dateFolder = new Date().toISOString().slice(0, 10);
  const dir = path.join(UPLOADS_DIR, dateFolder);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });

  const uniqueName = `${uuidv4()}${ext}`;
  fs.writeFileSync(path.join(dir, uniqueName), buffer);

  const fileUrl = `/uploads/${dateFolder}/${uniqueName}`;
  console.log(`[Upload /image-base64] OK  ${(buffer.length / 1024).toFixed(1)} KB  -> ${fileUrl}`);

  res.json({
    fileUrl,
    fileName: fileName || `clipboard-image${ext}`,
    fileSize: buffer.length,
  });
});

export default router;
