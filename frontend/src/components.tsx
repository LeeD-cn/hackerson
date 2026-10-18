import { useEffect, useRef, type ReactNode } from 'react';
import { ApiError } from './api';

export function Icon({ name, size = 20 }: { name: 'grid' | 'arrow' | 'plus' | 'refresh' | 'search' | 'close' | 'branch' | 'bell' | 'logout' | 'check' | 'edit'; size?: number }) {
  const paths = {
    grid: <><rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/></>,
    arrow: <><path d="M5 12h14M13 6l6 6-6 6"/></>,
    plus: <path d="M12 5v14M5 12h14"/>,
    refresh: <><path d="M20 8a8 8 0 1 0 0 8M20 3v5h-5"/></>,
    search: <><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></>,
    close: <path d="m6 6 12 12M18 6 6 18"/>,
    branch: <><circle cx="6" cy="5" r="2"/><circle cx="6" cy="19" r="2"/><circle cx="18" cy="5" r="2"/><path d="M6 7v10M18 7c0 6-12 2-12 8"/></>,
    bell: <><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M9 21h6"/></>,
    logout: <><path d="M10 4H4v16h6M10 12h11m-4-4 4 4-4 4"/></>,
    check: <path d="m5 12 4 4L19 6"/>,
    edit: <><path d="m14 5 5 5M4 20l5-1L20 8a2.8 2.8 0 0 0-4-4L5 15l-1 5Z"/></>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

export function ErrorNotice({ error, children }: { error: ApiError | null; children?: ReactNode }) {
  if (!error) return null;
  return <div className="error-box" role="alert"><strong>{error.status === 409 ? '当前内容已发生变化' : '操作未完成'}</strong><p>{error.message}</p>
    {error.details.length > 0 && <ul>{error.details.map((d, i) => <li key={i}>{d.field}：{d.message}</li>)}</ul>}{children}</div>;
}

export function Modal({ title, onClose, children, wide = false }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current!;
    dialog.showModal();
    // React's autoFocus can run while the native dialog is still closed.
    dialog.querySelector<HTMLInputElement>('input:not([disabled])')?.focus({ preventScroll: true });
    return () => dialog.close();
  }, []);
  return <dialog ref={ref} className={wide ? 'modal wide' : 'modal'} aria-label={title} onCancel={event => { event.preventDefault(); onClose(); }}>
    <div className="modal-heading"><div><span className="eyebrow">TASK WORKSPACE</span><h2>{title}</h2></div><button type="button" className="icon-button" aria-label="关闭窗口" onClick={onClose}><Icon name="close"/></button></div>
    {children}
  </dialog>;
}

export function TextBlock({ title, value }: { title: string; value: string | undefined }) {
  return <section className="text-block"><h3>{title}</h3><p className={!value ? 'muted' : ''}>{value || '尚未填写'}</p></section>;
}

export function formatTime(value: string) {
  return new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
}
