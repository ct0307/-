import axios, { type AxiosRequestConfig } from 'axios'
import { clearSessionStorage, SESSION_KEYS } from '@/utils/session'

// 响应拦截器返回的是 res.data（业务数据本体），不是 AxiosResponse。
// 用独立接口声明实例类型，让 api 层直接拿到泛型数据，避免逐处 as unknown as 双重断言。
export interface ApiClient {
  get<T = any>(url: string, config?: AxiosRequestConfig): Promise<T>
  delete<T = any>(url: string, config?: AxiosRequestConfig): Promise<T>
  post<T = any>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T>
  put<T = any>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T>
  patch<T = any>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T>
}

// 统一后端接口客户端。开发期经 vite proxy 转发到 :8000。
const instance = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
})

// 401 处理器由应用入口注册（登出 + router 跳转）。
// 拦截器不直接依赖 router / auth store，避免 client → store → api → client 的循环引用。
let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler
}

// 请求拦截：附带 JWT
instance.interceptors.request.use((config) => {
  const token = localStorage.getItem(SESSION_KEYS.token)
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截：统一错误处理。返回 res.data 便于业务直接拿数据。
const HTTP_ERROR_MSGS: Record<number, string> = {
  400: '请求参数有误',
  401: '登录已过期，请重新登录',
  403: '权限不足，无法执行此操作',
  404: '请求的资源不存在',
  422: '数据格式有误，请检查输入',
  429: '请求过于频繁，请稍后重试',
  500: '服务器内部错误',
  502: '服务网关异常',
  503: '服务暂时不可用，请稍后重试',
}

export function extractHttpErrorDetail(detail: unknown): { code?: string; message?: string } {
  if (!detail || typeof detail !== 'object') return {}
  const value = detail as { code?: unknown; message?: unknown; detail?: unknown }
  const message = typeof value.message === 'string'
    ? value.message
    : typeof value.detail === 'string'
      ? value.detail
      : undefined
  return {
    code: typeof value.code === 'string' ? value.code : undefined,
    message,
  }
}

instance.interceptors.response.use(
  (res) => res.data,
  (err) => {
    // 只清理发起请求时的会话，避免旧请求迟到的 401 注销新登录用户。
    const currentToken = localStorage.getItem(SESSION_KEYS.token)
    const requestAuthorization = err.config?.headers?.Authorization
    const belongsToCurrentSession = currentToken
      ? requestAuthorization === `Bearer ${currentToken}`
      : !requestAuthorization
    if (err.response?.status === 401 && belongsToCurrentSession) {
      clearSessionStorage()
      if (onUnauthorized) {
        onUnauthorized()
      } else if (location.pathname !== '/login') {
        // 兜底：处理器未注册时（如测试环境）整页跳转
        location.href = '/login'
      }
    }
    // 将 HTTP 状态码转为中文错误消息
    if (err.response?.status) {
      const status = err.response.status
      const detail = err.response.data?.detail
      const structuredDetail = extractHttpErrorDetail(detail)
      const safeDetail = structuredDetail.message ?? detail
      if (structuredDetail.code) err.code = structuredDetail.code
      // 只使用含中文字符的 detail，避免 FastAPI 自动生成的英文错误（如 "Internal Server Error"）直接展示
      const hasChinese = typeof safeDetail === 'string' && /[一-鿿]/.test(safeDetail)
      err.message = hasChinese
        ? safeDetail
        : (HTTP_ERROR_MSGS[status] ?? `请求失败（${status}）`)
    } else if (err.code === 'ECONNABORTED') {
      err.message = '请求超时，请检查网络后重试'
    } else if (!navigator.onLine) {
      err.message = '网络连接已断开，请检查网络'
    } else if (err.code === 'ERR_NETWORK') {
      err.message = '网络异常，无法连接到服务器'
    } else {
      err.message = err.message?.startsWith('Request failed')
        ? '网络请求失败，请稍后重试'
        : (err.message || '未知错误')
    }
    return Promise.reject(err)
  },
)

const client = instance as unknown as ApiClient

export default client
