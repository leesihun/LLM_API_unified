import { Router, Request, Response } from 'express';
import multer from 'multer';
import path from 'path';
import fs from 'fs';
import { v4 as uuidv4 } from 'uuid';

const UPLOADS_DIR = path.join(__dirname, '..', '..', 'uploads');

// Ensure uploads directory exists
if (!fs.existsSync(UPLOADS_DIR)) {
  fs.mkdirSync(UPLOADS_DIR, { recursive: true });
}

const storage = multer.diskStorage({
  destination: (_req, _file, cb) => {
    // Organize by date folders
    const dateFolder = new Date().toISOString().slice(0, 10);
    const dir = path.join(UPLOADS_DIR, dateFolder);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }
    cb(null, dir);
  },
  filename: (_req, file, cb) => {
    const ext = path.extname(file.originalname);
    const uniqueName = `${uuidv4()}${ext}`;
    cb(null, uniqueName);
  },
});

const upload = multer({
  storage,
  limits: { fileSize: 100 * 1024 * 1024 }, // 100MB
});

const router = Router();

// POST /upload/file - 파일 업로드
router.post('/file', upload.single('file'), (req: Request, res: Response) => {
  if (!req.file) {
    res.status(400).json({ error: '파일이 없습니다.' });
    return;
  }

  const dateFolder = new Date().toISOString().slice(0, 10);
  const fileUrl = `/uploads/${dateFolder}/${req.file.filename}`;
  const fileName = req.body.fileName || Buffer.from(req.file.originalname, 'latin1').toString('utf8');

  res.json({
    fileUrl,
    fileName,
    fileSize: req.file.size,
  });
});

// POST /upload/image-base64 - 클립보드 이미지 (base64) 업로드
router.post('/image-base64', (req: Request, res: Response) => {
  const { data, fileName } = req.body;

  if (!data) {
    res.status(400).json({ error: '이미지 데이터가 없습니다.' });
    return;
  }

  // Remove data URL prefix if present
  const base64Data = data.replace(/^data:image\/\w+;base64,/, '');
  const buffer = Buffer.from(base64Data, 'base64');

  // Determine extension from data URL or use png as default
  let ext = '.png';
  const mimeMatch = data.match(/^data:image\/(\w+);base64,/);
  if (mimeMatch) {
    ext = '.' + mimeMatch[1].replace('jpeg', 'jpg');
  }

  const dateFolder = new Date().toISOString().slice(0, 10);
  const dir = path.join(UPLOADS_DIR, dateFolder);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }

  const uniqueName = `${uuidv4()}${ext}`;
  const filePath = path.join(dir, uniqueName);

  fs.writeFileSync(filePath, buffer);

  const fileUrl = `/uploads/${dateFolder}/${uniqueName}`;

  res.json({
    fileUrl,
    fileName: fileName || `clipboard-image${ext}`,
    fileSize: buffer.length,
  });
});

export default router;
