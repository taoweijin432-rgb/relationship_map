import { createApp } from 'vue'
import {
  ElDialog,
  ElDrawer,
  ElDropdown,
  ElDropdownMenu,
  ElDropdownItem,
  ElTag,
  ElAlert,
  ElButton,
  ElCheckbox,
  ElDatePicker,
  ElForm,
  ElFormItem,
  ElIcon,
  ElInput,
  ElInputNumber,
  ElOption,
  ElSelect,
  ElSkeleton,
} from 'element-plus'
import 'element-plus/dist/index.css'
import App from './App.vue'
import './style.css'

const app = createApp(App)
for (const [name, component] of Object.entries({
  ElDialog,
  ElDrawer,
  ElDropdown,
  ElDropdownMenu,
  ElDropdownItem,
  ElTag,
  ElAlert,
  ElButton,
  ElCheckbox,
  ElDatePicker,
  ElForm,
  ElFormItem,
  ElIcon,
  ElInput,
  ElInputNumber,
  ElOption,
  ElSelect,
  ElSkeleton,
})) {
  app.component(name, component)
}
app.mount('#app')
