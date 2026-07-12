/**
 * Shared Socket.IO server instance. index.ts calls setIo() once at startup;
 * everything else (REST routes, socket handlers, pollers, message service)
 * reads it via getIo() instead of each module keeping its own setter.
 */
import type { Server } from 'socket.io';

let ioRef: Server<any, any> | null = null;

export function setIo(io: Server<any, any>) {
  ioRef = io;
}

export function getIo(): Server<any, any> | null {
  return ioRef;
}
