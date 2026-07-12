/**
 * /api — the external bot API, guarded by apiKeyAuth. One router per
 * resource; every path is unchanged from the original single-file router.
 */
import { Router } from 'express';
import { apiKeyAuth } from '../../middleware/apiAuth.js';
import messagesRouter from './messages.js';
import reactionsRouter from './reactions.js';
import roomsRouter from './rooms.js';
import botsRouter from './bots.js';
import typingRouter from './typing.js';
import webhooksRouter from './webhooks.js';
import watchersRouter from './watchers.js';

const router = Router();
router.use(apiKeyAuth);

router.use(messagesRouter);
router.use(reactionsRouter);
router.use(roomsRouter);
router.use(botsRouter);
router.use(typingRouter);
router.use(webhooksRouter);
router.use(watchersRouter);

export default router;
