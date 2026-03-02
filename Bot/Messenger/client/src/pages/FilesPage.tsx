import { useState, useEffect, useCallback, useRef } from 'react';
import api from '../services/api';

interface FileItem {
  name: string;
  isDirectory: boolean;
  size: number;
  modifiedAt: string;
  icon: string;
}

const FILE_ICONS: Record<string, string> = {
  folder: '📁',
  image: '🖼️',
  video: '🎬',
  audio: '🎵',
  document: '📄',
  code: '💻',
  archive: '📦',
  file: '📎',
};

function formatSize(bytes: number): string {
  if (bytes === 0) return '-';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

function formatDate(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleDateString('ko-KR', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export default function FilesPage() {
  const [currentPath, setCurrentPath] = useState('/');
  const [items, setItems] = useState<FileItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState('');
  const [showNewFolder, setShowNewFolder] = useState(false);
  const [newFolderName, setNewFolderName] = useState('');
  const [renamingItem, setRenamingItem] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; item: FileItem } | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const dragCounter = useRef(0);
  const renameInputRef = useRef<HTMLInputElement>(null);

  const fetchItems = useCallback(async () => {
    setLoading(true);
    setError('');
    setSelected(new Set());
    try {
      const res = await api.get(`/files/list?path=${encodeURIComponent(currentPath)}`);
      setItems(res.data.items);
    } catch (err: any) {
      setError(err.response?.data?.error || 'Failed to load files.');
    } finally {
      setLoading(false);
    }
  }, [currentPath]);

  useEffect(() => {
    fetchItems();
  }, [fetchItems]);

  useEffect(() => {
    if (renamingItem && renameInputRef.current) {
      renameInputRef.current.focus();
      renameInputRef.current.select();
    }
  }, [renamingItem]);

  useEffect(() => {
    const handleClick = () => setContextMenu(null);
    document.addEventListener('click', handleClick);
    return () => document.removeEventListener('click', handleClick);
  }, []);

  const navigate = (folderName: string) => {
    const newPath = currentPath === '/' ? `/${folderName}` : `${currentPath}/${folderName}`;
    setCurrentPath(newPath);
  };

  const navigateToPath = (targetPath: string) => {
    setCurrentPath(targetPath);
  };

  const breadcrumbs = (() => {
    const parts = currentPath.split('/').filter(Boolean);
    const crumbs = [{ name: 'Home', path: '/' }];
    let running = '';
    for (const part of parts) {
      running += `/${part}`;
      crumbs.push({ name: part, path: running });
    }
    return crumbs;
  })();

  const uploadFiles = async (files: FileList | File[]) => {
    if (files.length === 0) return;

    setUploading(true);
    setUploadProgress(`Uploading ${files.length} file(s)...`);

    const formData = new FormData();
    for (const file of Array.from(files)) {
      formData.append('files', file);
    }

    try {
      await api.post(`/files/upload?path=${encodeURIComponent(currentPath)}`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        onUploadProgress: (e) => {
          if (e.total) {
            const pct = Math.round((e.loaded / e.total) * 100);
            setUploadProgress(`Uploading... ${pct}%`);
          }
        },
      });
      await fetchItems();
    } catch (err: any) {
      setError(err.response?.data?.error || 'Upload failed.');
    } finally {
      setUploading(false);
      setUploadProgress('');
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      uploadFiles(e.target.files);
      e.target.value = '';
    }
  };

  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault();
    dragCounter.current++;
    setDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    dragCounter.current--;
    if (dragCounter.current === 0) setDragging(false);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    dragCounter.current = 0;
    setDragging(false);
    if (e.dataTransfer.files.length > 0) {
      uploadFiles(e.dataTransfer.files);
    }
  };

  const createFolder = async () => {
    if (!newFolderName.trim()) return;

    try {
      await api.post('/files/mkdir', { path: currentPath, name: newFolderName.trim() });
      setShowNewFolder(false);
      setNewFolderName('');
      await fetchItems();
    } catch (err: any) {
      setError(err.response?.data?.error || 'Failed to create folder.');
    }
  };

  const deleteItems = async (itemNames: string[]) => {
    if (!confirm(`Delete ${itemNames.length} item(s)?`)) return;

    try {
      for (const name of itemNames) {
        const itemPath = currentPath === '/' ? `/${name}` : `${currentPath}/${name}`;
        await api.post('/files/delete', { path: itemPath });
      }
      setSelected(new Set());
      await fetchItems();
    } catch (err: any) {
      setError(err.response?.data?.error || 'Failed to delete.');
    }
  };

  const renameItem = async (oldName: string) => {
    if (!renameValue.trim() || renameValue.trim() === oldName) {
      setRenamingItem(null);
      return;
    }

    const itemPath = currentPath === '/' ? `/${oldName}` : `${currentPath}/${oldName}`;

    try {
      await api.post('/files/rename', { path: itemPath, newName: renameValue.trim() });
      setRenamingItem(null);
      setRenameValue('');
      await fetchItems();
    } catch (err: any) {
      setError(err.response?.data?.error || 'Failed to rename.');
    }
  };

  const downloadFile = (name: string) => {
    const filePath = currentPath === '/' ? `/${name}` : `${currentPath}/${name}`;
    const url = `${api.defaults.baseURL}/files/download?path=${encodeURIComponent(filePath)}`;
    window.open(url, '_blank');
  };

  const toggleSelect = (name: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const handleItemClick = (item: FileItem) => {
    if (renamingItem) return;
    if (item.isDirectory) {
      navigate(item.name);
    }
  };

  const handleContextMenu = (e: React.MouseEvent, item: FileItem) => {
    e.preventDefault();
    setContextMenu({ x: e.clientX, y: e.clientY, item });
  };

  return (
    <div
      className="flex flex-col h-full bg-gray-50"
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="flex items-center justify-between mb-3">
          <h1 className="text-xl font-bold text-gray-800 flex items-center gap-2">
            <span className="text-2xl">📂</span>
            File Manager
          </h1>
          <div className="flex items-center gap-2">
            {selected.size > 0 && (
              <button
                onClick={() => deleteItems(Array.from(selected))}
                className="px-3 py-2 bg-red-50 text-red-600 rounded-lg text-sm font-medium hover:bg-red-100 transition flex items-center gap-1"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
                Delete ({selected.size})
              </button>
            )}
            <button
              onClick={() => setShowNewFolder(true)}
              className="px-3 py-2 bg-gray-100 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-200 transition flex items-center gap-1"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 13h6m-3-3v6m-9 1V7a2 2 0 012-2h6l2 2h6a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z" />
              </svg>
              New Folder
            </button>
            <button
              onClick={() => fileInputRef.current?.click()}
              className="px-3 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 transition flex items-center gap-1"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
              </svg>
              Upload
            </button>
            <input ref={fileInputRef} type="file" multiple className="hidden" onChange={handleFileSelect} />
          </div>
        </div>

        {/* Breadcrumbs */}
        <div className="flex items-center gap-1 text-sm">
          {breadcrumbs.map((crumb, idx) => (
            <span key={crumb.path} className="flex items-center gap-1">
              {idx > 0 && <span className="text-gray-300">/</span>}
              <button
                onClick={() => navigateToPath(crumb.path)}
                className={`hover:text-blue-600 transition px-1 py-0.5 rounded ${
                  idx === breadcrumbs.length - 1
                    ? 'text-gray-800 font-medium bg-gray-100'
                    : 'text-gray-500 hover:bg-gray-50'
                }`}
              >
                {crumb.name}
              </button>
            </span>
          ))}
        </div>
      </div>

      {/* Upload Progress */}
      {uploading && (
        <div className="bg-blue-50 px-6 py-2 text-sm text-blue-700 flex items-center gap-2">
          <div className="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
          {uploadProgress}
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="bg-red-50 px-6 py-2 text-sm text-red-600 flex items-center justify-between">
          {error}
          <button onClick={() => setError('')} className="text-red-400 hover:text-red-600">
            ✕
          </button>
        </div>
      )}

      {/* New Folder Modal */}
      {showNewFolder && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setShowNewFolder(false)}>
          <div className="bg-white rounded-2xl shadow-2xl p-6 w-full max-w-sm" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-semibold text-gray-800 mb-4">New Folder</h3>
            <input
              type="text"
              value={newFolderName}
              onChange={(e) => setNewFolderName(e.target.value)}
              placeholder="Folder name"
              className="w-full px-4 py-2.5 border border-gray-300 rounded-lg outline-none focus:ring-2 focus:ring-blue-500 text-sm mb-4"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === 'Enter') createFolder();
                if (e.key === 'Escape') setShowNewFolder(false);
              }}
            />
            <div className="flex gap-2">
              <button
                onClick={() => setShowNewFolder(false)}
                className="flex-1 py-2 bg-gray-100 text-gray-600 rounded-lg hover:bg-gray-200 transition text-sm"
              >
                Cancel
              </button>
              <button
                onClick={createFolder}
                className="flex-1 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition text-sm"
              >
                Create
              </button>
            </div>
          </div>
        </div>
      )}

      {/* File List */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {loading ? (
          <div className="flex items-center justify-center h-full text-gray-400">
            <div className="w-6 h-6 border-2 border-gray-300 border-t-blue-500 rounded-full animate-spin mr-2" />
            Loading...
          </div>
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-gray-400">
            <span className="text-5xl mb-3">📂</span>
            <p className="text-lg">This folder is empty</p>
            <p className="text-sm mt-1">Drag & drop files here or click Upload</p>
          </div>
        ) : (
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            {/* Table Header */}
            <div className="grid grid-cols-[auto_1fr_100px_160px_80px] gap-4 px-4 py-2.5 bg-gray-50 border-b border-gray-200 text-xs font-medium text-gray-500 uppercase tracking-wider">
              <div className="w-6" />
              <div>Name</div>
              <div className="text-right">Size</div>
              <div>Modified</div>
              <div />
            </div>

            {/* Items */}
            {items.map((item) => (
              <div
                key={item.name}
                className={`grid grid-cols-[auto_1fr_100px_160px_80px] gap-4 px-4 py-2.5 border-b border-gray-100 last:border-0 hover:bg-gray-50 transition cursor-pointer group items-center ${
                  selected.has(item.name) ? 'bg-blue-50' : ''
                }`}
                onClick={() => handleItemClick(item)}
                onContextMenu={(e) => handleContextMenu(e, item)}
                onDoubleClick={() => {
                  if (!item.isDirectory) downloadFile(item.name);
                }}
              >
                {/* Checkbox */}
                <div>
                  <input
                    type="checkbox"
                    checked={selected.has(item.name)}
                    onChange={() => {}}
                    onClick={(e) => toggleSelect(item.name, e)}
                    className="accent-blue-600 cursor-pointer"
                  />
                </div>

                {/* Name */}
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-lg flex-shrink-0">{FILE_ICONS[item.icon] || '📎'}</span>
                  {renamingItem === item.name ? (
                    <input
                      ref={renameInputRef}
                      type="text"
                      value={renameValue}
                      onChange={(e) => setRenameValue(e.target.value)}
                      onBlur={() => renameItem(item.name)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') renameItem(item.name);
                        if (e.key === 'Escape') setRenamingItem(null);
                      }}
                      onClick={(e) => e.stopPropagation()}
                      className="px-2 py-0.5 border border-blue-400 rounded text-sm outline-none focus:ring-1 focus:ring-blue-500 min-w-0 flex-1"
                    />
                  ) : (
                    <span className={`text-sm truncate ${item.isDirectory ? 'font-medium text-gray-800' : 'text-gray-700'}`}>
                      {item.name}
                    </span>
                  )}
                </div>

                {/* Size */}
                <div className="text-right text-xs text-gray-500">
                  {formatSize(item.size)}
                </div>

                {/* Modified */}
                <div className="text-xs text-gray-400">
                  {formatDate(item.modifiedAt)}
                </div>

                {/* Actions */}
                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition">
                  {!item.isDirectory && (
                    <button
                      onClick={(e) => { e.stopPropagation(); downloadFile(item.name); }}
                      className="p-1 text-gray-400 hover:text-blue-600 transition"
                      title="Download"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                      </svg>
                    </button>
                  )}
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setRenamingItem(item.name);
                      setRenameValue(item.name);
                    }}
                    className="p-1 text-gray-400 hover:text-yellow-600 transition"
                    title="Rename"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                    </svg>
                  </button>
                  <button
                    onClick={(e) => { e.stopPropagation(); deleteItems([item.name]); }}
                    className="p-1 text-gray-400 hover:text-red-600 transition"
                    title="Delete"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Drag overlay */}
      {dragging && (
        <div className="absolute inset-0 bg-blue-500/10 border-2 border-dashed border-blue-400 rounded-xl z-40 flex items-center justify-center pointer-events-none">
          <div className="bg-white rounded-2xl shadow-xl px-8 py-6 text-center">
            <span className="text-4xl block mb-2">📥</span>
            <p className="text-lg font-medium text-blue-600">Drop files here to upload</p>
            <p className="text-sm text-gray-400 mt-1">Files will be uploaded to: {currentPath}</p>
          </div>
        </div>
      )}

      {/* Context Menu */}
      {contextMenu && (
        <div
          className="fixed bg-white border border-gray-200 rounded-lg shadow-lg py-1 z-50 min-w-[140px]"
          style={{ left: contextMenu.x, top: contextMenu.y }}
        >
          {contextMenu.item.isDirectory && (
            <button
              onClick={() => { navigate(contextMenu.item.name); setContextMenu(null); }}
              className="block w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-100"
            >
              Open
            </button>
          )}
          {!contextMenu.item.isDirectory && (
            <button
              onClick={() => { downloadFile(contextMenu.item.name); setContextMenu(null); }}
              className="block w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-100"
            >
              Download
            </button>
          )}
          <button
            onClick={() => {
              setRenamingItem(contextMenu.item.name);
              setRenameValue(contextMenu.item.name);
              setContextMenu(null);
            }}
            className="block w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-100"
          >
            Rename
          </button>
          <button
            onClick={() => { deleteItems([contextMenu.item.name]); setContextMenu(null); }}
            className="block w-full text-left px-4 py-2 text-sm text-red-500 hover:bg-gray-100"
          >
            Delete
          </button>
        </div>
      )}

      {/* Footer info */}
      <div className="bg-white border-t border-gray-200 px-6 py-2 text-xs text-gray-400 flex items-center justify-between">
        <span>{items.length} item(s)</span>
        <span>
          Total: {formatSize(items.reduce((sum, i) => sum + i.size, 0))}
        </span>
      </div>
    </div>
  );
}
