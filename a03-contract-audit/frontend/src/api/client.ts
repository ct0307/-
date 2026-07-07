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
    return Promise.reject(err)
  },
)

export default client
