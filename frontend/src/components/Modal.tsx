import { useEffect, useRef, type ReactNode } from 'react'
import Icon from './Icon'
export default function Modal({ title, onClose, children, wide = false }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const dialog = ref.current!
    const previous = document.activeElement as HTMLElement | null
    dialog.showModal()
    return () => { dialog.close(); previous?.focus() }
  }, [])
  return <dialog ref={ref} className={`modal ${wide ? 'modal-wide' : ''}`} aria-label={title}
    onCancel={(event) => { event.preventDefault(); onClose() }}
    onClick={(event) => { if (event.target === event.currentTarget) onClose() }}>
    <div className="modal-content"><header className="section-heading"><h2>{title}</h2><button className="icon-button" aria-label={`关闭${title}`} onClick={onClose}><Icon name="close" /></button></header>{children}</div>
  </dialog>
}
