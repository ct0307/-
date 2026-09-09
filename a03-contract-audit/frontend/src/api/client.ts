import axios from 'axios'

// 统一后端接口客户端。开发期经 vite proxy 转发到 :8000。
const client = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
})

// 请求拦截：附带 JWT
client.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
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

client.interceptors.response.use(
  (res) => res.data,
  (err) => {
    // 401：凭证失效，清 token 跳登录
    if (err.response?.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('role')
      if (location.pathname !== '/login') {
        location.href = '/login'
      }
    }
    // 将 HTTP 状态码转为中文错误消息
    if (err.response?.status) {
      const status = err.response.status
      const detail = err.response.data?.detail
      const structuredDetail = detail && typeof detail === 'object'
        ? detail as { code?: unknown; detail?: unknown }
        : null
      const safeDetail = structuredDetail?.detail ?? detail
      if (structuredDetail && typeof structuredDetail.code === 'string') {
        err.code = structuredDetail.code
      }
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

export default client
