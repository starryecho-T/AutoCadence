import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
  /** 恢复回调；根级传 () => location.reload()，卡片级通过递增 key 重挂该卡片。未提供时仅重置错误状态。 */
  onReset?: () => void
  resetLabel?: string
}

interface State { error: Error | null }

/** 渲染异常隔离：捕获子树渲染错误，显示提示与恢复按钮，避免整窗白屏。 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('AutoCadence 页面区域渲染异常：', error, info.componentStack)
  }

  private reset = () => {
    this.setState({ error: null })
    this.props.onReset?.()
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children
    return <div className="note err" role="alert" style={{ margin: '12px 0' }}>
      <strong>页面出错，已隔离</strong>
      <p className="muted small">{error.message || String(error)}</p>
      <button className="btn ghost" onClick={this.reset}>{this.props.resetLabel ?? '重试本区域'}</button>
    </div>
  }
}
