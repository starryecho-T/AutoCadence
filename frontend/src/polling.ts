/** 下一次查询在上一次结束后开始；停止时取消请求并丢弃迟到的响应。 */
export function pollSequentially<T>(options: {
  read: (signal: AbortSignal) => Promise<T>
  onValue: (value: T) => void
  isDone: (value: T) => boolean
  onError: (error: unknown) => void
  intervalMs: number
}): () => void {
  const controller = new AbortController()
  let timer: ReturnType<typeof setTimeout> | undefined
  async function tick() {
    try {
      const value = await options.read(controller.signal)
      if (controller.signal.aborted) return
      options.onValue(value)
      if (!options.isDone(value) && !controller.signal.aborted) timer = setTimeout(tick, options.intervalMs)
    } catch (error) {
      if (!controller.signal.aborted) options.onError(error)
    }
  }
  void tick()
  return () => { controller.abort(); clearTimeout(timer) }
}
