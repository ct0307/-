// 按需注册项目实际用到的 Element Plus 图标（替代全量注册减包）。
// 覆盖三类用法：组件形式 <Icon/>、字符串 :icon="'Name'"、nav.ts 的 <component :is>。
import type { App } from 'vue'
import {
  Bell,
  Clock,
  Coin,
  Collection,
  DataAnalysis,
  Delete,
  Document,
  DocumentChecked,
  Download,
  EditPen,
  Files,
  InfoFilled,
  Lock,
  MagicStick,
  Odometer,
  Plus,
  Search,
  SetUp,
  Stamp,
  SwitchButton,
  UploadFilled,
  User,
} from '@element-plus/icons-vue'

const ICONS = {
  Bell,
  Clock,
  Coin,
  Collection,
  DataAnalysis,
  Delete,
  Document,
  DocumentChecked,
  Download,
  EditPen,
  Files,
  InfoFilled,
  Lock,
  MagicStick,
  Odometer,
  Plus,
  Search,
  SetUp,
  Stamp,
  SwitchButton,
  UploadFilled,
  User,
}

export function registerIcons(app: App) {
  for (const [name, comp] of Object.entries(ICONS)) {
    app.component(name, comp)
  }
}
