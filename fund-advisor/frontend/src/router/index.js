import { createRouter, createWebHistory } from 'vue-router'

import DashboardView from '../views/DashboardView.vue'
import HoldingsView from '../views/HoldingsView.vue'
import FundDetailView from '../views/FundDetailView.vue'
import ImportView from '../views/ImportView.vue'
import AnalysisView from '../views/AnalysisView.vue'
import CalendarView from '../views/CalendarView.vue'
import SettingsView from '../views/SettingsView.vue'
import AdvisorView from '../views/AdvisorView.vue'
import RecommendView from '../views/RecommendView.vue'
import SimulatorView from '../views/SimulatorView.vue'
import AdaptiveView from '../views/AdaptiveView.vue'
import PlanView from '../views/PlanView.vue'

const routes = [
  {
    path: '/',
    name: 'Dashboard',
    component: DashboardView,
    meta: { title: '仪表盘' },
  },
  {
    path: '/advisor',
    name: 'Advisor',
    component: AdvisorView,
    meta: { title: 'AI 顾问' },
  },
  {
    path: '/recommend',
    name: 'Recommend',
    component: RecommendView,
    meta: { title: '荐基 & 择时' },
  },
  {
    path: '/simulator',
    name: 'Simulator',
    component: SimulatorView,
    meta: { title: '策略回测' },
  },
  {
    path: '/plan',
    name: 'Plan',
    component: PlanView,
    meta: { title: '投资方案' },
  },
  {
    path: '/adaptive',
    name: 'Adaptive',
    component: AdaptiveView,
    meta: { title: '自适应优化' },
  },
  {
    path: '/holdings',
    name: 'Holdings',
    component: HoldingsView,
    meta: { title: '持仓列表' },
  },
  {
    path: '/funds/:code',
    name: 'FundDetail',
    component: FundDetailView,
    meta: { title: '基金详情' },
  },
  {
    path: '/import',
    name: 'Import',
    component: ImportView,
    meta: { title: '数据导入' },
  },
  {
    path: '/analysis',
    name: 'Analysis',
    component: AnalysisView,
    meta: { title: '投资分析' },
  },
  {
    path: '/calendar',
    name: 'Calendar',
    component: CalendarView,
    meta: { title: '收益日历' },
  },
  {
    path: '/settings',
    name: 'Settings',
    component: SettingsView,
    meta: { title: '设置' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to) => {
  document.title = to.meta.title
    ? `${to.meta.title} - 基金组合追踪器`
    : '基金组合追踪器'
})

export default router
