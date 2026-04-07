    const { createApp } = Vue;
    const API_BASE = '/api/v1';

    createApp({
      data() {
        const now = new Date();
        return {
          authReady: false,
          authToken: '',
          currentUser: null,
          loginForm: {
            username: '',
            password: '',
          },
          users: [],
          userSearch: '',
          userForm: {
            id: null,
            username: '',
            full_name: '',
            email: '',
            phone: '',
            team: 'SRE',
            role: 'operator',
            password: '',
          },
          userFormMaskedPhone: '',
          userFormPhoneCache: '',
          phoneEditUnlocked: true,
          schedules: [],
          selectedScheduleIds: [],
          selectedScheduleId: null,
          selectedSchedule: null,
          currentOncall: null,
          monthDate: new Date(now.getFullYear(), now.getMonth(), 1),
          activeFeature: 'alerts',
          scheduleView: 'list',
          activeTab: 'calendar',
          loading: false,
          showAddUserModal: false,
          showAddScheduleModal: false,
          showGroupModal: false,
          normalShifts: [],
          specialShifts: [],
          incidents: [],
          selectedIncidentId: null,
          selectedIncident: null,
          selectedIncidents: [],
          incidentPage: 1,
          incidentPageSize: 20,
          hasNextIncidentPage: false,
          resendingLark: false,
          incidentStatusFilter: 'open',
          alertScope: 'mine',
          incidentKeyword: '',
          refreshCountdown: 30,
          serverTimezone: 'Asia/Shanghai',
          serverUtcOffset: '+08:00',
          integrations: [],
          larkAppConfig: {
            enabled: false,
            app_id: '',
            app_secret: '',
          },
          nightingaleAuth: {
            enabled: false,
            username: '',
            has_password: false,
            updated_at: null,
          },
          nightingaleAuthForm: {
            username: 'root',
          },
          nightingaleGeneratedPassword: '',
          nightingalePasswordVisible: false,
          nightingaleLoading: false,
          integrationForm: {
            source_key: '',
            name: '',
            description: '',
          },
          scheduleIntegration: {
            lark_enabled: false,
            lark_chat_id: '',
            cti_values_text: '',
            escalation_enabled: true,
            escalation_after_minutes: 60,
            ack_escalation_enabled: true,
            ack_escalation_after_minutes: 15,
            notify_all_oncall_on_ack_timeout: true,
            important_direct_phone: true,
            huawei_phone_api_url: '',
            huawei_target_phones_text: '',
          },
          generatingCti: false,
          testEvent: {
            hash: '',
            title: '',
            summary: '',
            severity: 'critical',
          },
          newUser: {
            username: '',
            full_name: '',
            email: '',
            phone: '',
            password: '',
          },
          newSchedule: {
            name: '',
            description: '',
            start_date: '',
            owner_id: null,
            member_ids: [],
          },
          newScheduleGroups: [{ primary: null, secondary: null }],
          editingGroupRows: [],
          form: {
            id: null,
            shift_date: '',
            shift_type: 'full_day',
            role: 'primary',
            user_id: null,
            notes: '',
          },
          importText: '',
          overwrite: false,
        };
      },
      computed: {
        isAdmin() {
          return (this.currentUser?.role || '').toLowerCase() === 'admin';
        },
        roleDisplayName() {
          return this.isAdmin ? '管理员' : '普通用户';
        },
        filteredUsers() {
          const q = (this.userSearch || '').trim().toLowerCase();
          if (!q) return this.users;
          return this.users.filter((u) => {
            return [u.full_name, u.username, u.email, u.team]
              .filter(Boolean)
              .some((val) => String(val).toLowerCase().includes(q));
          });
        },
        weekdays() {
          return ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
        },
        monthTitle() {
          return `${this.monthDate.getFullYear()}年${this.monthDate.getMonth() + 1}月`;
        },
        scheduleUsers() {
          const memberIds = new Set(this.selectedSchedule?.member_ids || []);
          return this.users.filter((user) => memberIds.has(user.id));
        },
        scheduleOwnerName() {
          if (!this.selectedSchedule) return '-';
          if (this.selectedSchedule.owner_name) return this.selectedSchedule.owner_name;
          if (this.selectedSchedule.owner_id) {
            const owner = this.users.find((u) => u.id === this.selectedSchedule.owner_id);
            return owner?.full_name || `用户#${this.selectedSchedule.owner_id}`;
          }
          return '-';
        },
        scheduleCtiValues() {
          return (this.scheduleIntegration.cti_values_text || '')
            .split(',')
            .map((item) => item.trim())
            .filter(Boolean);
        },
        specialRows() {
          return [...this.specialShifts].sort((a, b) => {
            const dateCompare = (a.shift_date || '').localeCompare(b.shift_date || '');
            if (dateCompare !== 0) return dateCompare;
            return `${a.shift_type}_${a.role}`.localeCompare(`${b.shift_type}_${b.role}`);
          });
        },
        memberGroupRows() {
          const ids = this.selectedSchedule?.member_ids || [];
          const byId = new Map(this.users.map((u) => [u.id, u.full_name]));
          const rows = [];
          for (let i = 0; i < ids.length; i += 2) {
            rows.push({
              primary: byId.get(ids[i]) || null,
              secondary: byId.get(ids[i + 1]) || null,
            });
          }
          return rows;
        },
        monthRange() {
          const start = new Date(this.monthDate.getFullYear(), this.monthDate.getMonth(), 1);
          const end = new Date(this.monthDate.getFullYear(), this.monthDate.getMonth() + 1, 0);
          const format = (date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
          return { start: format(start), end: format(end) };
        },
        calendarCells() {
          const year = this.monthDate.getFullYear();
          const month = this.monthDate.getMonth();
          const firstDay = new Date(year, month, 1);
          const firstWeekday = firstDay.getDay();
          const daysInMonth = new Date(year, month + 1, 0).getDate();
          const normalMap = this.buildNormalMap();
          const specialMap = this.buildSpecialMap();
          const cells = [];

          for (let i = 0; i < firstWeekday; i++) {
            const d = new Date(year, month, i - firstWeekday + 1);
            cells.push(this.makeCell(d, false, normalMap, specialMap));
          }
          for (let day = 1; day <= daysInMonth; day++) {
            cells.push(this.makeCell(new Date(year, month, day), true, normalMap, specialMap));
          }
          while (cells.length % 7 !== 0) {
            const d = new Date(year, month + 1, cells.length - (firstWeekday + daysInMonth) + 1);
            cells.push(this.makeCell(d, false, normalMap, specialMap));
          }
          return cells;
        },
        incidentTimeline() {
          if (!this.selectedIncident) return [];
          const eventItems = (this.selectedIncident.events || []).map((event) => {
            const status = event.event_status;
            const isRecovered = status === 'resolved' || status === 'recovered';
            return {
              key: `event-${event.id}`,
              time: event.occurred_at,
              title: `事件 · ${isRecovered ? '恢复' : '触发'}`,
              subtitle: `${event.severity || 'unknown'} · ${this.resolveEventDisplayTitle(event)}`,
              content: this.buildEventTimelineContent(event),
              milestone: isRecovered ? '已恢复' : '触发',
              milestoneType: isRecovered ? 'recovered' : 'triggered',
              eventStatus: status,
            };
          });
          const logItems = (this.selectedIncident.action_logs || []).map((log) => ({
            key: `log-${log.id}`,
            time: log.created_at,
            title: `操作 · ${log.action}`,
            subtitle: log.actor_user?.full_name || '系统',
            content: log.message,
            milestone: this.getActionMilestone(log.action),
          }));
          const notificationItems = (this.selectedIncident.notifications || []).map((notification) => ({
            key: `notification-${notification.id}`,
            time: notification.created_at,
            title: `通知 · ${notification.status}`,
            subtitle: `${notification.channel} → ${notification.recipient || '未命中接收人'}`,
            content: notification.subject,
            milestone: notification.status === 'sent' || notification.status === 'simulated' ? '已发送' : null,
          }));
          return [...eventItems, ...logItems, ...notificationItems].sort((a, b) => this.parseBackendDateTime(b.time) - this.parseBackendDateTime(a.time));
        },
        incidentStats() {
          return {
            open: this.incidents.filter(i => i.status === 'open').length,
            acknowledged: this.incidents.filter(i => i.status === 'acknowledged').length,
            resolved: this.incidents.filter(i => i.status === 'resolved').length,
          };
        },
        selectedVisibleIncidentCount() {
          const visibleIds = new Set(this.incidents.map((incident) => this.incidentIdKey(incident.id)));
          return this.selectedIncidents.filter((id) => visibleIds.has(this.incidentIdKey(id))).length;
        },
        allVisibleIncidentsSelected() {
          if (!this.incidents.length) return false;
          return this.selectedVisibleIncidentCount === this.incidents.length;
        },
        alertPanelTitle() {
          if (this.alertScope === 'mine' && this.currentUser) {
            return `${this.currentUser.full_name} 相关告警`;
          }
          return '全部告警';
        },
        alertPanelDescription() {
          const scopeText = this.alertScope === 'mine' && this.currentUser
            ? '默认展示当前登录用户相关的告警（负责人 / 已认领 / 已关闭 / 已通知）'
            : '展示当前筛选范围内的全部告警';
          const scheduleText = this.selectedSchedule ? `，当前排班：${this.selectedSchedule.name}` : '，未选择排班时跨排班聚合展示';
          return `${scopeText}${scheduleText}`;
        },
        selectedVisibleScheduleCount() {
          const visibleIds = new Set(this.schedules.map((schedule) => this.scheduleIdKey(schedule.id)));
          return this.selectedScheduleIds.filter((id) => visibleIds.has(this.scheduleIdKey(id))).length;
        },
        allVisibleSchedulesSelected() {
          if (!this.schedules.length) return false;
          return this.selectedVisibleScheduleCount === this.schedules.length;
        },
        canManageSelectedSchedule() {
          return this.canManageSchedule(this.selectedSchedule);
        },
        canManageVisibleSchedules() {
          return this.schedules.some((schedule) => this.canManageSchedule(schedule));
        },
      },
      watch: {
        activeFeature(newValue) {
          if (newValue === 'integrations' && this.isAdmin) {
            this.loadNightingaleWebhookAuth(true);
            return;
          }
          this.nightingaleGeneratedPassword = '';
          this.nightingalePasswordVisible = false;
        },
      },
      methods: {
        setupAxiosInterceptors() {
          axios.interceptors.response.use(
            (response) => response,
            (error) => {
              if (error?.response?.status === 401 && this.authToken) {
                this.clearAuth();
                alert('登录已过期，请重新登录');
              }
              return Promise.reject(error);
            },
          );
        },
        readStoredToken() {
          return window.localStorage.getItem('accessToken') || '';
        },
        applyAuthHeader(token = '') {
          if (token) {
            axios.defaults.headers.common.Authorization = `Bearer ${token}`;
          } else {
            delete axios.defaults.headers.common.Authorization;
          }
        },
        async initializeAuth() {
          const token = this.readStoredToken();
          if (!token) {
            this.authReady = true;
            return;
          }
          this.authToken = token;
          this.applyAuthHeader(token);
          try {
            await this.loadMe();
          } catch (error) {
            this.clearAuth();
          } finally {
            this.authReady = true;
          }
        },
        async loadMe() {
          const res = await axios.get(`${API_BASE}/auth/me`);
          this.currentUser = res.data;
        },
        async login() {
          if (!this.loginForm.username || !this.loginForm.password) {
            alert('请输入用户名/邮箱和密码');
            return;
          }
          try {
            const res = await axios.post(`${API_BASE}/auth/login`, this.loginForm);
            const token = res.data?.access_token || '';
            if (!token) {
              throw new Error('登录成功但未返回 access_token');
            }
            this.authToken = token;
            this.currentUser = res.data?.user || null;
            window.localStorage.setItem('accessToken', token);
            this.applyAuthHeader(token);
            this.loginForm.password = '';
            await this.reloadAll();
            await this.applyDeepLink();
          } catch (error) {
            alert(error.response?.data?.detail || error.message);
          }
        },
        clearAuth() {
          this.authToken = '';
          this.currentUser = null;
          window.localStorage.removeItem('accessToken');
          this.applyAuthHeader('');
          this.selectedScheduleIds = [];
          this.incidents = [];
          this.selectedIncident = null;
          this.selectedIncidentId = null;
          this.selectedIncidents = [];
        },
        ensureAdminAction() {
          if (this.isAdmin) return true;
          alert('仅管理员可执行该操作');
          return false;
        },
        canManageSchedule(schedule) {
          if (!schedule || !this.currentUser?.id) return false;
          if (this.isAdmin) return true;
          return (schedule.member_ids || []).includes(this.currentUser.id);
        },
        ensureScheduleManageAction(schedule = this.selectedSchedule) {
          if (this.canManageSchedule(schedule)) return true;
          alert('只能管理自己相关的排班表');
          return false;
        },
        logout() {
          this.clearAuth();
          this.loginForm = { username: '', password: '' };
          this.authReady = true;
        },
        async openAlertsView() {
          this.activeFeature = 'alerts';
          await this.loadAlertDataFromFirstPage();
        },
        async loadAlertDataFromFirstPage() {
          this.incidentPage = 1;
          await this.loadAlertData(false);
        },
        async changeIncidentPage(delta) {
          const nextPage = this.incidentPage + delta;
          if (nextPage < 1) return;
          if (delta > 0 && !this.hasNextIncidentPage) return;
          this.incidentPage = nextPage;
          await this.loadAlertData(false);
        },
        async setIncidentPageSize(size) {
          const parsed = Number(size);
          if (![20, 50, 100].includes(parsed)) return;
          if (this.incidentPageSize === parsed) return;
          this.incidentPageSize = parsed;
          this.incidentPage = 1;
          await this.loadAlertData(false);
        },
        async reloadAll() {
          if (!this.currentUser) return;
          const tasks = [this.loadUsers(), this.loadSchedules(), this.loadLarkAppConfig()];
          if (this.isAdmin) {
            tasks.push(this.loadNightingaleWebhookAuth(true));
          }
          await Promise.all(tasks);
          if (this.selectedScheduleId) {
            await this.selectSchedule(this.selectedScheduleId);
          } else if (this.activeFeature === 'alerts') {
            await this.loadAlertData(false);
          }
        },
        async loadServerTimeMeta() {
          try {
            const res = await axios.get(`${API_BASE}/server-time-meta`);
            const data = res.data || {};
            if (data.timezone) {
              this.serverTimezone = String(data.timezone);
            }
            if (data.utc_offset) {
              this.serverUtcOffset = String(data.utc_offset);
            }
          } catch (error) {
            console.warn('loadServerTimeMeta failed, fallback to defaults:', error?.message || error);
          }
        },
        async applyDeepLink() {
          const params = new URLSearchParams(window.location.search || '');
          const feature = params.get('feature');
          const scheduleId = Number(params.get('schedule_id') || 0);
          const incidentId = Number(params.get('incident_id') || 0);

          if (!feature && !scheduleId && !incidentId) return;

          if (feature) {
            const isAdminOnlyFeature = feature === 'users' || feature === 'integrations';
            this.activeFeature = (isAdminOnlyFeature && !this.isAdmin) ? 'schedule' : feature;
          }

          if (feature === 'alerts' && !scheduleId && !incidentId) {
            await this.loadAlertData(false);
          }

          if (scheduleId) {
            await this.selectSchedule(scheduleId);
          }

          if (incidentId) {
            this.activeFeature = 'alerts';
            if (!this.incidents.length) {
              await this.loadAlertData(false);
            }
            await this.selectIncident(incidentId);
          }
        },
        defaultScheduleIntegration() {
          return {
            lark_enabled: false,
            lark_chat_id: '',
            cti_values_text: '',
            escalation_enabled: true,
            escalation_after_minutes: 60,
            ack_escalation_enabled: true,
            ack_escalation_after_minutes: 15,
            notify_all_oncall_on_ack_timeout: true,
            important_direct_phone: true,
            huawei_phone_api_url: '',
            huawei_target_phones_text: '',
          };
        },
        async loadLarkAppConfig() {
          try {
            const res = await axios.get(`${API_BASE}/lark-app-config`);
            const data = res.data || {};
            this.larkAppConfig = {
              enabled: !!data.enabled,
              app_id: data.app_id || '',
              app_secret: data.app_secret || '',
            };
          } catch (error) {
            this.larkAppConfig = { enabled: false, app_id: '', app_secret: '' };
          }
        },
        async saveLarkAppConfig() {
          if (!this.ensureAdminAction()) return;
          try {
            await axios.post(`${API_BASE}/lark-app-config`, {
              enabled: !!this.larkAppConfig.enabled,
              app_id: this.larkAppConfig.app_id || null,
              app_secret: this.larkAppConfig.app_secret || null,
            });
            await this.loadLarkAppConfig();
            alert('统一 Lark 应用配置已保存');
          } catch (error) {
            alert(error.response?.data?.detail || error.message);
          }
        },
        async loadNightingaleWebhookAuth(silent = false) {
          if (!this.isAdmin) return;
          try {
            const res = await axios.get(`${API_BASE}/nightingale-webhook-auth`);
            const data = res.data || {};
            this.nightingaleAuth = {
              enabled: !!data.enabled,
              username: data.username || '',
              has_password: !!data.has_password,
              updated_at: data.updated_at || null,
            };
          } catch (error) {
            if (!silent) {
              alert(error.response?.data?.detail || error.message);
            }
          }
        },
        async generateNightingaleWebhookAuth() {
          if (!this.ensureAdminAction()) return;
          this.nightingaleLoading = true;
          try {
            const res = await axios.post(`${API_BASE}/nightingale-webhook-auth/generate`, {
              username: (this.nightingaleAuthForm.username || '').trim() || null,
            });
            const data = res.data || {};
            this.nightingaleGeneratedPassword = data.password || '';
            this.nightingalePasswordVisible = true;  // show plaintext immediately after generation
            this.nightingaleAuth = {
              enabled: !!data.enabled,
              username: data.username || '',
              has_password: !!data.has_password,
              updated_at: data.updated_at || null,
            };
            if (!this.nightingaleGeneratedPassword) {
              alert('生成成功，但未返回密码，请重试');
            }
          } catch (error) {
            alert(error.response?.data?.detail || error.message);
          } finally {
            this.nightingaleLoading = false;
          }
        },
        async disableNightingaleWebhookAuth() {
          if (!this.ensureAdminAction()) return;
          if (!confirm('确认禁用 Nightingale Webhook Basic Auth 吗？')) return;
          this.nightingaleLoading = true;
          try {
            const res = await axios.post(`${API_BASE}/nightingale-webhook-auth/disable`);
            const data = res.data || {};
            this.nightingaleGeneratedPassword = '';
            this.nightingalePasswordVisible = false;
            this.nightingaleAuth = {
              enabled: !!data.enabled,
              username: data.username || '',
              has_password: !!data.has_password,
              updated_at: data.updated_at || null,
            };
          } catch (error) {
            alert(error.response?.data?.detail || error.message);
          } finally {
            this.nightingaleLoading = false;
          }
        },
        dismissNightingalePassword() {
          this.nightingaleGeneratedPassword = '';
          this.nightingalePasswordVisible = false;
        },
        toggleNightingalePasswordVisible() {
          this.nightingalePasswordVisible = !this.nightingalePasswordVisible;
        },
        maskSecret(value) {
          const raw = String(value || '');
          if (!raw) return '';
          if (raw.length <= 6) return '*'.repeat(raw.length);
          return `${raw.slice(0, 2)}${'*'.repeat(raw.length - 4)}${raw.slice(-2)}`;
        },
        async copyNightingalePassword() {
          if (!this.nightingaleGeneratedPassword) return;
          try {
            if (navigator?.clipboard?.writeText) {
              await navigator.clipboard.writeText(this.nightingaleGeneratedPassword);
            } else {
              throw new Error('clipboard not available');
            }
            alert('密码已复制');
          } catch (error) {
            alert(`复制失败，请手动复制：${error?.message || error}`);
          }
        },
        async copyNightingaleWebhookUrl() {
          if (!this.nightingaleWebhookUrl) return;
          try {
            if (navigator?.clipboard?.writeText) {
              await navigator.clipboard.writeText(this.nightingaleWebhookUrl);
            } else {
              throw new Error('clipboard not available');
            }
            alert('Webhook URL 已复制，直接粘贴到 Nightingale 的 URL 字段');
          } catch (error) {
            alert(`复制失败，请手动复制：${error?.message || error}`);
          }
        },
        async loadUsers() {
          const res = await axios.get(`${API_BASE}/users/`);
          this.users = res.data || [];
        },
        async loadSchedules() {
          const res = await axios.get(`${API_BASE}/schedules/`);
          this.schedules = res.data || [];
          const visibleIds = new Set(this.schedules.map((schedule) => this.scheduleIdKey(schedule.id)));
          this.selectedScheduleIds = this.selectedScheduleIds
            .map((id) => this.scheduleIdKey(id))
            .filter((id) => visibleIds.has(id));
        },
        scheduleIdKey(scheduleId) {
          return String(scheduleId);
        },
        toggleScheduleSelect(scheduleId) {
          const key = this.scheduleIdKey(scheduleId);
          const idx = this.selectedScheduleIds.findIndex((id) => this.scheduleIdKey(id) === key);
          if (idx > -1) {
            this.selectedScheduleIds.splice(idx, 1);
          } else {
            this.selectedScheduleIds.push(key);
          }
        },
        toggleSelectAllSchedules() {
          const visibleIds = this.schedules.map((schedule) => this.scheduleIdKey(schedule.id));
          if (!visibleIds.length) return;

          if (this.allVisibleSchedulesSelected) {
            const visibleSet = new Set(visibleIds);
            this.selectedScheduleIds = this.selectedScheduleIds.filter((id) => !visibleSet.has(this.scheduleIdKey(id)));
            return;
          }

          const merged = new Set(this.selectedScheduleIds.map((id) => this.scheduleIdKey(id)));
          for (const id of visibleIds) {
            merged.add(id);
          }
          this.selectedScheduleIds = Array.from(merged);
        },
        clearScheduleSelection() {
          this.selectedScheduleIds = [];
        },
        async batchDeleteSchedules() {
          if (!this.canManageVisibleSchedules) {
            alert('当前没有可管理的排班表');
            return;
          }
          if (!this.selectedScheduleIds.length) {
            alert('请先选择要删除的排班表');
            return;
          }
          if (!confirm(`确认批量删除已选 ${this.selectedScheduleIds.length} 个排班表吗？（将停用，不会硬删除数据）`)) return;
          try {
            const payloadIds = this.selectedScheduleIds
              .map((id) => Number(id))
              .filter((id) => Number.isInteger(id));
            const res = await axios.post(`${API_BASE}/schedules/batch-delete`, {
              schedule_ids: payloadIds,
            });
            const deletedCount = res.data?.deleted_count || 0;
            const notFound = res.data?.not_found_ids || [];
            await this.loadSchedules();

            if (this.selectedScheduleId && payloadIds.includes(Number(this.selectedScheduleId))) {
              this.selectedScheduleId = null;
              this.selectedSchedule = null;
              this.currentOncall = null;
              this.scheduleView = 'list';
            }
            this.clearScheduleSelection();
            const notFoundText = notFound.length ? `\n未找到: ${notFound.join(', ')}` : '';
            const forbidden = res.data?.forbidden_ids || [];
            const forbiddenText = forbidden.length ? `\n无权限: ${forbidden.join(', ')}` : '';
            alert(`批量删除完成：停用 ${deletedCount} 个排班表${notFoundText}${forbiddenText}`);
          } catch (error) {
            alert(error.response?.data?.detail || error.message);
          }
        },
        async addUser() {
          if (!this.ensureAdminAction()) return;
          // 兼容旧入口：跳转到左侧「人员管理」
          this.activeFeature = 'users';
          this.openUserCreate();
        },
        openUserCreate() {
          if (!this.ensureAdminAction()) return;
          this.userForm = { id: null, username: '', full_name: '', email: '', phone: '', team: 'SRE', role: 'operator', password: '' };
          this.userFormMaskedPhone = '';
          this.userFormPhoneCache = '';
          this.phoneEditUnlocked = true;
        },
        openUserEdit(user) {
          if (!this.ensureAdminAction()) return;
          this.userForm = {
            id: user.id,
            username: user.username,
            full_name: user.full_name,
            email: user.email,
            phone: '',
            team: user.team || 'SRE',
            role: user.role || 'operator',
            password: '',
          };
          this.userFormMaskedPhone = user.masked_phone || '';
          this.userFormPhoneCache = user.phone || '';
          this.phoneEditUnlocked = false;
        },
        resetUserForm() {
          this.openUserCreate();
        },
        unlockPhoneEdit() {
          this.phoneEditUnlocked = true;
          this.userForm.phone = this.userFormPhoneCache;
        },
        async saveUser() {
          if (!this.ensureAdminAction()) return;
          if (!this.userForm.username || !this.userForm.full_name || !this.userForm.email) {
            alert('请至少填写用户名、姓名、邮箱');
            return;
          }
          try {
            if (this.userForm.id) {
              const payload = {
                email: this.userForm.email,
                full_name: this.userForm.full_name,
                team: this.userForm.team || null,
                role: this.userForm.role || 'operator',
              };
              if (this.phoneEditUnlocked) {
                payload.phone = this.userForm.phone || null;
              }
              await axios.put(`${API_BASE}/users/${this.userForm.id}`, payload);
            } else {
              if (!this.userForm.password) {
                alert('新增人员需要设置初始密码');
                return;
              }
              await axios.post(`${API_BASE}/users/`, {
                username: this.userForm.username,
                full_name: this.userForm.full_name,
                email: this.userForm.email,
                phone: this.userForm.phone || null,
                team: this.userForm.team || 'SRE',
                role: this.userForm.role || 'operator',
                password: this.userForm.password,
              });
            }
            await this.loadUsers();
            this.resetUserForm();
          } catch (error) {
            alert(error.response?.data?.detail || error.message);
          }
        },
        async deleteUser(user) {
          if (!this.ensureAdminAction()) return;
          if (!confirm(`确认删除 ${user.full_name} 吗？删除后将不再出现在人员列表。`)) return;
          try {
            await axios.delete(`${API_BASE}/users/${user.id}`);
            if (this.userForm.id === user.id) {
              this.resetUserForm();
            }
            await this.loadUsers();
          } catch (error) {
            alert(error.response?.data?.detail || error.message);
          }
        },
        async addSchedule() {
          if (!this.ensureAdminAction()) return;
          if (!this.newSchedule.name || !this.newSchedule.start_date) {
            alert('请至少填写排班名称和开始日期');
            return;
          }
          if (!this.newSchedule.owner_id) {
            alert('请先选择排班负责人');
            return;
          }
          const memberIds = [];
          for (const row of this.newScheduleGroups) {
            if (row.primary) memberIds.push(row.primary);
            if (row.secondary) memberIds.push(row.secondary);
          }
          const payload = {
            name: this.newSchedule.name,
            description: this.newSchedule.description || null,
            start_date: `${this.newSchedule.start_date}T00:00:00`,
            end_date: null,
            owner_id: this.newSchedule.owner_id || null,
            member_ids: memberIds,
          };
          try {
            const created = await axios.post(`${API_BASE}/schedules/`, payload);
            this.showAddScheduleModal = false;
            this.newSchedule = { name: '', description: '', start_date: '', owner_id: null, member_ids: [] };
            this.newScheduleGroups = [{ primary: null, secondary: null }];
            await this.loadSchedules();
            if (created.data?.id) {
              await this.selectSchedule(created.data.id);
            }
          } catch (error) {
            alert(error.response?.data?.detail || error.message);
          }
        },

        async toggleScheduleActive() {
          if (!this.ensureScheduleManageAction()) return;
          if (!this.selectedScheduleId || !this.selectedSchedule) return;
          try {
            await axios.put(`${API_BASE}/schedules/${this.selectedScheduleId}`, {
              is_active: !this.selectedSchedule.is_active,
            });
            await this.loadSchedules();
            await this.loadSelectedSchedule();
          } catch (error) {
            alert(error.response?.data?.detail || error.message);
          }
        },

        async deleteSchedule() {
          if (!this.ensureScheduleManageAction()) return;
          if (!this.selectedScheduleId || !this.selectedSchedule) return;
          if (!confirm(`确认删除排班表「${this.selectedSchedule.name}」吗？（将停用，不会硬删除数据）`)) return;
          try {
            await axios.delete(`${API_BASE}/schedules/${this.selectedScheduleId}`);
            await this.loadSchedules();
            // back to schedule list
            this.selectedScheduleId = null;
            this.selectedSchedule = null;
            this.currentOncall = null;
            this.scheduleView = 'list';
          } catch (error) {
            alert(error.response?.data?.detail || error.message);
          }
        },
        addCreateGroupRow() {
          this.newScheduleGroups.push({ primary: null, secondary: null });
        },
        removeCreateGroupRow(index) {
          this.newScheduleGroups.splice(index, 1);
          if (this.newScheduleGroups.length === 0) {
            this.newScheduleGroups.push({ primary: null, secondary: null });
          }
        },
        openGroupModal() {
          if (!this.ensureScheduleManageAction()) return;
          const ids = this.selectedSchedule?.member_ids || [];
          const rows = [];
          for (let i = 0; i < ids.length; i += 2) {
            rows.push({ primary: ids[i] || null, secondary: ids[i + 1] || null });
          }
          this.editingGroupRows = rows.length ? rows : [{ primary: null, secondary: null }];
          this.showGroupModal = true;
        },
        addGroupRow() {
          this.editingGroupRows.push({ primary: null, secondary: null });
        },
        removeGroupRow(index) {
          this.editingGroupRows.splice(index, 1);
          if (this.editingGroupRows.length === 0) {
            this.editingGroupRows.push({ primary: null, secondary: null });
          }
        },
        async saveGroupRows() {
          if (!this.ensureScheduleManageAction()) return;
          if (!this.selectedScheduleId) return;
          const memberIds = [];
          for (const row of this.editingGroupRows) {
            if (row.primary) memberIds.push(row.primary);
            if (row.secondary) memberIds.push(row.secondary);
          }
          try {
            await axios.put(`${API_BASE}/schedules/${this.selectedScheduleId}`, { member_ids: memberIds });
            await axios.post(`${API_BASE}/schedules/${this.selectedScheduleId}/generate`, {
              start_date: this.monthRange.start,
              end_date: this.monthRange.end,
              include_secondary: true,
              regenerate: true,
            });
            this.showGroupModal = false;
            await this.loadSelectedSchedule();
            await this.loadSchedules();
            await this.loadDetailData();
          } catch (error) {
            alert(error.response?.data?.detail || error.message);
          }
        },
        async saveScheduleOwner() {
          if (!this.ensureScheduleManageAction()) return;
          if (!this.selectedScheduleId) return;
          if (!this.selectedSchedule?.owner_id) {
            alert('负责人不能为空');
            return;
          }
          try {
            await axios.put(`${API_BASE}/schedules/${this.selectedScheduleId}`, {
              owner_id: this.selectedSchedule?.owner_id || null,
            });
            await this.loadSchedules();
            await this.loadSelectedSchedule();
          } catch (error) {
            alert(error.response?.data?.detail || error.message);
          }
        },
        async sendTodayReminder() {
          if (!this.ensureScheduleManageAction()) return;
          if (!this.selectedScheduleId || !this.selectedSchedule) return;
          try {
            const res = await axios.post(`${API_BASE}/schedules/${this.selectedScheduleId}/send-today-reminder`);
            const status = res.data?.status || 'unknown';
            const error = res.data?.error_message ? `\n${res.data.error_message}` : '';
            alert(`发送结果：${status}${error}`);
          } catch (error) {
            alert(error.response?.data?.detail || error.message);
          }
        },
        async selectSchedule(scheduleId) {
          this.selectedScheduleId = scheduleId;
          this.activeTab = 'calendar';
          this.selectedIncidentId = null;
          this.selectedIncident = null;
          this.selectedIncidents = [];
          this.integrationForm = { source_key: '', name: '', description: '' };
          await this.loadSelectedSchedule();
          await this.loadDetailData();
          await this.loadAlertData(false);
        },

        async openScheduleDetail(scheduleId) {
          this.activeFeature = 'schedule';
          this.scheduleView = 'detail';
          await this.selectSchedule(scheduleId);
        },

        openScheduleList() {
          this.activeFeature = 'schedule';
          this.scheduleView = 'list';
          // keep selection but hide detail panels
        },
        async handleIntegrationScheduleChange(event) {
          const value = event?.target?.value;
          if (!value) {
            this.selectedScheduleId = null;
            this.selectedSchedule = null;
            this.currentOncall = null;
            this.integrations = [];
            this.scheduleIntegration = this.defaultScheduleIntegration();
            this.selectedIncidentId = null;
            this.selectedIncident = null;
            this.selectedIncidents = [];
            this.syncIntegrationForm();
            return;
          }
          await this.selectSchedule(Number(value));
        },
        async loadSelectedSchedule() {
          if (!this.selectedScheduleId) return;
          const [scheduleRes, currentRes] = await Promise.allSettled([
            axios.get(`${API_BASE}/schedules/${this.selectedScheduleId}`),
            axios.get(`${API_BASE}/schedules/${this.selectedScheduleId}/current`),
          ]);
          this.selectedSchedule = scheduleRes.status === 'fulfilled' ? scheduleRes.value.data : null;
          this.currentOncall = currentRes.status === 'fulfilled' ? currentRes.value.data : null;
          if (!this.integrationForm.source_key) {
            this.syncIntegrationForm();
          }

          await this.loadScheduleIntegration();
        },

        async loadScheduleIntegration() {
          if (!this.selectedScheduleId) return;
          try {
            const res = await axios.get(`${API_BASE}/schedules/${this.selectedScheduleId}/integrations`);
            const data = res.data || {};
            this.scheduleIntegration = {
              lark_enabled: !!data.lark_enabled,
              lark_chat_id: data.lark_chat_id || '',
              cti_values_text: (data.cti_values || []).join(',') || '',
              escalation_enabled: data.escalation_enabled !== false,
              escalation_after_minutes: data.escalation_after_minutes || 60,
              ack_escalation_enabled: data.ack_escalation_enabled !== false,
              ack_escalation_after_minutes: data.ack_escalation_after_minutes || 15,
              notify_all_oncall_on_ack_timeout: data.notify_all_oncall_on_ack_timeout !== false,
              important_direct_phone: data.important_direct_phone !== false,
              huawei_phone_api_url: data.huawei_phone_api_url || '',
              huawei_target_phones_text: (data.huawei_target_phones || []).join(',') || '',
            };
          } catch (error) {
            // ignore if not configured yet
            this.scheduleIntegration = this.defaultScheduleIntegration();
          }
        },
        async loadDetailData() {
          if (!this.selectedScheduleId) return;
          this.loading = true;
          try {
            const shiftRes = await axios.get(`${API_BASE}/shifts/`, {
              params: {
                schedule_id: this.selectedScheduleId,
                start_date: `${this.monthRange.start}T00:00:00`,
                end_date: `${this.monthRange.end}T23:59:59`,
              }
            });
            const specialRes = await axios.get(`${API_BASE}/special-shifts/`, {
              params: {
                schedule_id: this.selectedScheduleId,
                start_date: this.monthRange.start,
                end_date: this.monthRange.end,
              }
            });
            this.normalShifts = shiftRes.data || [];
            this.specialShifts = specialRes.data || [];
          } finally {
            this.loading = false;
          }
        },
        buildDefaultSourceKey() {
          if (!this.selectedScheduleId) return 'default-source';
          return `schedule-${this.selectedScheduleId}-default`;
        },
        syncIntegrationForm(source = null) {
          const defaultKey = source?.source_key || this.integrationForm.source_key || this.buildDefaultSourceKey();
          this.integrationForm = {
            source_key: defaultKey,
            name: source?.name || `${this.selectedSchedule?.name || 'Oncall'} 告警接入`,
            description: source?.description || '',
          };
        },
        useIntegration(source) {
          this.syncIntegrationForm(source);
        },
        async loadAlertData(keepSelection = true) {
          const incidentParams = {};
          if (this.selectedScheduleId) {
            incidentParams.schedule_id = this.selectedScheduleId;
          }
          if (this.incidentStatusFilter && this.incidentStatusFilter !== 'all') {
            incidentParams.status = this.incidentStatusFilter;
          }
          if (this.alertScope === 'mine' && this.currentUser?.id) {
            incidentParams.user_id = this.currentUser.id;
            incidentParams.related_only = true;
          }
          if ((this.incidentKeyword || '').trim()) {
            incidentParams.keyword = this.incidentKeyword.trim();
          }
          const pageSize = Number(this.incidentPageSize) || 20;
          incidentParams.skip = Math.max((this.incidentPage - 1) * pageSize, 0);
          incidentParams.limit = pageSize + 1;

          const requests = [axios.get('/incidents', { params: incidentParams })];
          if (this.selectedScheduleId) {
            requests.push(axios.get('/integrations', { params: { schedule_id: this.selectedScheduleId } }));
          }
          const [incidentRes, integrationRes] = await Promise.all(requests);
          const rows = incidentRes.data || [];
          this.hasNextIncidentPage = rows.length > pageSize;
          this.incidents = this.hasNextIncidentPage ? rows.slice(0, pageSize) : rows;
          this.integrations = integrationRes?.data || [];
          const visibleIds = new Set(this.incidents.map((incident) => this.incidentIdKey(incident.id)));
          this.selectedIncidents = this.selectedIncidents
            .map((id) => this.incidentIdKey(id))
            .filter((id) => visibleIds.has(id));

          if (this.selectedScheduleId && this.integrations.length) {
            const matched = this.integrations.find((item) => item.source_key === this.integrationForm.source_key);
            this.useIntegration(matched || this.integrations[0]);
          } else if (this.selectedScheduleId) {
            this.syncIntegrationForm();
          } else {
            this.integrations = [];
          }

          if (keepSelection && this.selectedIncidentId) {
            const exists = this.incidents.find((item) => item.id === this.selectedIncidentId);
            if (exists) {
              await this.loadIncidentDetail(this.selectedIncidentId);
              return;
            }
          }

          if (this.incidents.length) {
            await this.selectIncident(this.incidents[0].id);
          } else {
            this.selectedIncidentId = null;
            this.selectedIncident = null;
          }
        },
        async selectIncident(incidentId) {
          this.selectedIncidentId = incidentId;
          await this.loadIncidentDetail(incidentId);
        },
        async loadIncidentDetail(incidentId) {
          const res = await axios.get(`/incidents/${incidentId}`);
          this.selectedIncident = res.data;
          this.selectedIncidentId = res.data?.id || incidentId;
        },
        async saveScheduleIntegration() {
          if (!this.ensureAdminAction()) return;
          if (!this.selectedScheduleId) {
            alert('请先选择排班表');
            return;
          }
          try {
            await axios.post(`${API_BASE}/schedules/${this.selectedScheduleId}/integrations`, {
              source_key: this.integrationForm.source_key || this.buildDefaultSourceKey(),
              source_name: this.integrationForm.name || `${this.selectedSchedule?.name || 'Oncall'} 默认接入`,
              lark_enabled: !!this.scheduleIntegration.lark_enabled,
              lark_chat_id: this.scheduleIntegration.lark_chat_id || null,
              cti_values: (this.scheduleIntegration.cti_values_text || '')
                .split(',')
                .map(item => item.trim())
                .filter(Boolean),
              escalation_enabled: this.scheduleIntegration.escalation_enabled !== false,
              escalation_after_minutes: Number(this.scheduleIntegration.escalation_after_minutes || 60),
              ack_escalation_enabled: this.scheduleIntegration.ack_escalation_enabled !== false,
              ack_escalation_after_minutes: Number(this.scheduleIntegration.ack_escalation_after_minutes || 15),
              notify_all_oncall_on_ack_timeout: this.scheduleIntegration.notify_all_oncall_on_ack_timeout !== false,
              important_direct_phone: this.scheduleIntegration.important_direct_phone !== false,
              huawei_phone_api_url: this.scheduleIntegration.huawei_phone_api_url || null,
              huawei_target_phones: (this.scheduleIntegration.huawei_target_phones_text || '')
                .split(',')
                .map(item => item.trim())
                .filter(Boolean),
            });
            await this.loadScheduleIntegration();
            await this.loadAlertData(false);
          } catch (error) {
            alert(error.response?.data?.detail || error.message);
          }
        },
        async generateScheduleCti() {
          if (!this.ensureScheduleManageAction()) return;
          if (!this.selectedScheduleId) {
            alert('请先选择排班表');
            return;
          }
          this.generatingCti = true;
          try {
            const res = await axios.post(`${API_BASE}/schedules/${this.selectedScheduleId}/integrations/generate-cti`);
            const values = res.data?.cti_values || [];
            this.scheduleIntegration.cti_values_text = values.join(',');
            await this.loadSchedules();
            await this.loadSelectedSchedule();
          } catch (error) {
            alert(error.response?.data?.detail || error.message);
          } finally {
            this.generatingCti = false;
          }
        },
        async triggerTestEvent(eventStatus) {
          if (!this.ensureAdminAction()) return;
          if (!this.selectedScheduleId) {
            alert('请先选择排班表');
            return;
          }
          if (!this.testEvent.hash || !this.testEvent.title) {
            alert('请填写 hash 和事件标题');
            return;
          }
          try {
            await this.saveScheduleIntegration();

            const ctiValues = (this.scheduleIntegration.cti_values_text || '')
              .split(',')
              .map(item => item.trim())
              .filter(Boolean);
            const cti = ctiValues[0];
            if (!cti) {
              alert('请先在接入配置中设置 CTI 标签值（至少一个）');
              return;
            }

            const nowIso = new Date().toISOString();
            const res = await axios.post('/open-api/events', {
              hash: this.testEvent.hash,
              event_id: `ui-${Date.now()}-${eventStatus}`,
              cti,
              rule_name: this.testEvent.title,
              title: this.testEvent.title,
              source_name: 'Nightingale',
              severity: this.testEvent.severity,
              status: eventStatus,
              event_status: eventStatus,
              trigger_time: nowIso,
              summary: this.testEvent.summary || null,
              is_recovered: eventStatus === 'resolved',
              cluster: 'prometheus-local',
              prom_ql: 'demo_oncall_qps <50',
              payload: {
                from: 'static-index',
                schedule_id: this.selectedScheduleId,
                nightingale_origin: true,
                rule_name: this.testEvent.title,
                status: eventStatus,
                event_status: eventStatus,
                trigger_time: nowIso,
                hash: this.testEvent.hash,
              },
            });
            await this.loadAlertData(false);
            if (res.data?.incident?.id) {
              await this.selectIncident(res.data.incident.id);
            }
          } catch (error) {
            alert(error.response?.data?.detail || error.message);
          }
        },
        async ackIncident() {
          if (!this.selectedIncident || this.selectedIncident.status === 'resolved') return;
          try {
            const res = await axios.post(`/incidents/${this.selectedIncident.id}/ack`, {
              user_id: this.currentUser?.id || this.selectedIncident.assigned_user_id || this.currentOncall?.user?.id || null,
              note: '已通过界面认领',
            });
            this.selectedIncident = res.data;
            await this.loadAlertData(true);
          } catch (error) {
            alert(error.response?.data?.detail || error.message);
          }
        },
        async resolveIncident() {
          if (!this.selectedIncident) return;
          try {
            const res = await axios.post(`/incidents/${this.selectedIncident.id}/resolve`, {
              user_id: this.currentUser?.id || this.selectedIncident.assigned_user_id || this.currentOncall?.user?.id || null,
              note: '已通过界面关闭',
            });
            this.selectedIncident = res.data;
            await this.loadAlertData(true);
          } catch (error) {
            alert(error.response?.data?.detail || error.message);
          }
        },
        async resendLarkTicket() {
          if (!this.selectedIncident) return;
          this.resendingLark = true;
          try {
            const res = await axios.post(`/incidents/${this.selectedIncident.id}/resend-lark-ticket`);
            const data = res.data || {};
            if (data.lark_status === 'sent') {
              alert(`✅ Lark Ticket 已重新发送\nIncident ID: I${data.incident_id}\n消息 ID: ${data.message_id || '-'}`);
            } else if (data.lark_status === 'skipped') {
              alert(`⚠️ 未发送：${data.error_message || '请检查 Lark 配置'}`);
            } else {
              alert(`❌ 发送失败：${data.error_message || '未知错误'}`);
            }
          } catch (error) {
            alert(error.response?.data?.detail || error.message);
          } finally {
            this.resendingLark = false;
          }
        },
        incidentStatusClass(status) {
          const mapping = {
            open: 'bg-rose-100 text-rose-700',
            acknowledged: 'bg-amber-100 text-amber-700',
            resolved: 'bg-emerald-100 text-emerald-700',
          };
          return mapping[status] || 'bg-slate-100 text-slate-600';
        },
        severityClass(severity) {
          const mapping = {
            critical: 'bg-rose-100 text-rose-700',
            warning: 'bg-amber-100 text-amber-700',
            info: 'bg-blue-100 text-blue-700',
          };
          return mapping[severity] || 'bg-slate-100 text-slate-600';
        },
        statusText(status) {
          const mapping = {
            open: '未认领',
            acknowledged: '已认领',
            resolved: '已关闭',
          };
          return mapping[status] || status;
        },
        eventStatusText(status) {
          const mapping = {
            triggered: '触发',
            resolved: '恢复',
            recovered: '恢复',
          };
          return mapping[status] || status;
        },
        resolveEventDisplayTitle(event) {
          const payload = event?.payload || {};
          const raw = String(event?.title || payload.rule_name || '').trim();
          if (!raw) return 'Nightingale Alert';
          if (raw.includes('{{$value}}') || raw.includes('{{ $value }}')) {
            const value = payload.trigger_value ?? payload.last_eval_value ?? payload.value ?? payload.eval_value;
            if (value !== undefined && value !== null && String(value).trim()) {
              return raw.replace('{{$value}}', String(value)).replace('{{ $value }}', String(value));
            }
            return raw.replace('{{$value}}', '').replace('{{ $value }}', '').trim() || raw;
          }
          return raw;
        },
        buildEventTimelineContent(event) {
          const payload = event?.payload || {};
          const hash = payload.hash || event?.hash || event?.fingerprint;
          const status = event?.event_status;
          const isRecovered = status === 'resolved' || status === 'recovered';

          if (isRecovered) {
            const lines = ['告警已恢复正常。'];
            if (hash) lines.push(`hash=${hash}`);
            return lines.join('\n');
          }

          if (event?.summary) {
            return event.summary;
          }

          const lines = [];
          const value = payload.trigger_value ?? payload.last_eval_value ?? payload.value ?? payload.eval_value;
          if (value !== undefined && value !== null && String(value).trim()) {
            lines.push(`当前值=${value}`);
          }
          const target = payload.target_ident || payload.target;
          if (target) {
            lines.push(`目标=${target}`);
          }
          const ql = payload.prom_ql || payload.ql;
          if (ql) {
            const qlText = String(ql);
            lines.push(`PromQL=${qlText.length > 160 ? `${qlText.slice(0, 160)}...` : qlText}`);
          }
          if (hash) {
            lines.push(`hash=${hash}`);
          }
          return lines.join('\n') || '无额外内容';
        },
        coverageSummary(coverage) {
          const fullDay = coverage?.assignments?.full_day || {};
          const primary = fullDay.primary?.full_name || '-';
          const secondary = fullDay.secondary?.full_name || '-';
          return `主：${primary} / 副：${secondary}`;
        },
        changeMonth(offset) {
          this.monthDate = new Date(this.monthDate.getFullYear(), this.monthDate.getMonth() + offset, 1);
          this.loadDetailData();
        },
        makeCell(date, currentMonth, normalMap, specialMap) {
          const dateStr = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
          return {
            key: `${currentMonth ? 'cur' : 'other'}-${dateStr}`,
            day: date.getDate(),
            dateStr,
            currentMonth,
            assignments: normalMap[dateStr] || { full_day: { primary: null, secondary: null } },
            specials: specialMap[dateStr] || [],
          };
        },
        dateOnlyFromValue(value) {
          if (!value) return null;
          const text = String(value);
          const match = text.match(/^(\d{4})-(\d{2})-(\d{2})/);
          if (match) {
            return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
          }
          const parsed = new Date(value);
          if (Number.isNaN(parsed.getTime())) return null;
          return new Date(parsed.getFullYear(), parsed.getMonth(), parsed.getDate());
        },
        diffDays(baseDate, targetDate) {
          const baseUtc = Date.UTC(baseDate.getFullYear(), baseDate.getMonth(), baseDate.getDate());
          const targetUtc = Date.UTC(targetDate.getFullYear(), targetDate.getMonth(), targetDate.getDate());
          return Math.floor((targetUtc - baseUtc) / 86400000);
        },
        buildNormalMap() {
          const grouped = {};
          const byId = new Map(this.users.map((u) => [u.id, u.full_name]));
          for (const shift of this.normalShifts || []) {
            const dateStr = shift.shift_date || String(shift.start_time || '').slice(0, 10);
            if (!dateStr) continue;
            if (!grouped[dateStr]) {
              grouped[dateStr] = { full_day: { primary: null, secondary: null } };
            }
            const roleKey = shift.role === 'secondary' ? 'secondary' : 'primary';
            grouped[dateStr].full_day[roleKey] = shift.user?.full_name || byId.get(shift.user_id) || `用户#${shift.user_id}`;
          }
          return grouped;
        },
        buildSpecialMap() {
          const grouped = {};
          for (const shift of this.specialShifts) {
            const day = shift.shift_date;
            if (!grouped[day]) grouped[day] = [];
            grouped[day].push(shift);
          }
          return grouped;
        },
        shiftLabel(shiftType, role) {
          const typeText = '24 小时';
          const roleText = role === 'secondary' ? '副值班' : '主值班';
          return `${typeText}${roleText}`;
        },
        buildSpecialWindow(shiftDate, shiftType) {
          const handover = this.selectedSchedule?.handover_hour ?? 9;
          const start = new Date(`${shiftDate}T00:00:00`);
          const dayStart = new Date(start);
          dayStart.setHours(handover, 0, 0, 0);
          const dayEnd = new Date(dayStart);
          dayEnd.setDate(dayEnd.getDate() + 1);
          return { start: dayStart, end: dayEnd };
        },
        resetForm() {
          this.form = {
            id: null,
            shift_date: this.monthRange.start,
            shift_type: 'full_day',
            role: 'primary',
            user_id: this.scheduleUsers[0]?.id || null,
            notes: '',
          };
          this.activeTab = 'special';
        },
        editRow(row) {
          if (!this.ensureScheduleManageAction(this.selectedSchedule)) return;
          this.form = {
            id: row.id,
            shift_date: row.shift_date,
            shift_type: row.shift_type,
            role: row.role,
            user_id: row.user_id,
            notes: row.notes || '',
          };
        },
        async saveSpecialShift() {
          if (!this.ensureScheduleManageAction()) return;
          if (!this.selectedScheduleId || !this.form.shift_date || !this.form.user_id) {
            alert('请先选择排班表，并填写日期和值班人');
            return;
          }
          const timeWindow = this.buildSpecialWindow(this.form.shift_date, this.form.shift_type);
          const payload = {
            schedule_id: this.selectedScheduleId,
            shift_date: this.form.shift_date,
            shift_type: this.form.shift_type,
            role: this.form.role,
            user_id: this.form.user_id,
            notes: this.form.notes || null,
            start_time: timeWindow.start.toISOString(),
            end_time: timeWindow.end.toISOString(),
            is_locked: true,
          };
          try {
            if (this.form.id) {
              await axios.put(`${API_BASE}/special-shifts/${this.form.id}`, payload);
            } else {
              await axios.post(`${API_BASE}/special-shifts/`, payload);
            }
            this.resetForm();
            await this.loadDetailData();
          } catch (error) {
            alert(error.response?.data?.detail || error.message);
          }
        },
        async deleteRow(row) {
          if (!this.ensureScheduleManageAction()) return;
          if (!confirm('确认删除该特殊排班吗？')) return;
          try {
            await axios.delete(`${API_BASE}/special-shifts/${row.id}`);
            if (this.form.id === row.id) this.resetForm();
            await this.loadDetailData();
          } catch (error) {
            alert(error.response?.data?.detail || error.message);
          }
        },
        openImportExample() {
          if (!this.canManageSelectedSchedule) return;
          const defaultUser = this.scheduleUsers[0]?.id || 1;
          this.importText = JSON.stringify([
            {
              user_id: defaultUser,
              shift_date: this.monthRange.start,
              shift_type: 'full_day',
              role: 'primary',
              notes: '节假日保障',
            }
          ], null, 2);
          this.activeTab = 'special';
        },
        async bulkImport() {
          if (!this.ensureScheduleManageAction()) return;
          if (!this.selectedScheduleId) {
            alert('请先选择排班表');
            return;
          }
          let items;
          try {
            items = JSON.parse(this.importText || '[]');
            if (!Array.isArray(items)) {
              throw new Error('导入内容必须是 JSON 数组');
            }
          } catch (error) {
            alert(error.message || 'JSON 格式错误');
            return;
          }
          try {
            const res = await axios.post(`${API_BASE}/special-shifts/schedules/${this.selectedScheduleId}/bulk`, {
              items,
              overwrite: this.overwrite,
            });
            const result = res.data;
            const preview = (result.failures || []).slice(0, 5).map(item => `#${item.index + 1} ${item.reason}`).join('\n');
            alert(`导入完成：成功 ${result.created_count} 条，失败 ${result.failed_count} 条${preview ? `\n${preview}` : ''}`);
            await this.loadDetailData();
          } catch (error) {
            alert(error.response?.data?.detail || error.message);
          }
        },
        formatDate(value) {
          if (!value) return '-';
          const parsed = this.parseBackendDateTime(value);
          if (Number.isNaN(parsed.getTime())) return String(value);
          return parsed.toLocaleDateString('zh-CN', {
            timeZone: this.serverTimezone || undefined,
          });
        },
        parseBackendDateTime(value) {
          if (!value) return new Date(NaN);
          if (value instanceof Date) return value;

          const text = String(value).trim();
          // Backend may return naive server-time strings without timezone suffix.
          if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?$/.test(text)) {
            return new Date(`${text}${this.serverUtcOffset || '+00:00'}`);
          }
          return new Date(text);
        },
        formatDateTime(value) {
          if (!value) return '-';
          const parsed = this.parseBackendDateTime(value);
          if (Number.isNaN(parsed.getTime())) return String(value);
          return parsed.toLocaleString('zh-CN', {
            hour12: false,
            timeZone: this.serverTimezone || undefined,
          });
        },
        timeSinceCreated(createdAt) {
          if (!createdAt) return '-';
          const now = new Date();
          const created = this.parseBackendDateTime(createdAt);
          if (Number.isNaN(created.getTime())) return '-';
          const diffMs = now - created;
          const diffMins = Math.floor(diffMs / 60000);
          if (diffMins < 1) return '刚刚';
          if (diffMins < 60) return `${diffMins}分钟前`;
          const diffHours = Math.floor(diffMins / 60);
          if (diffHours < 24) return `${diffHours}小时前`;
          const diffDays = Math.floor(diffHours / 24);
          return `${diffDays}天前`;
        },
        minutesSince(time) {
          if (!time) return '-';
          const now = new Date();
          const at = this.parseBackendDateTime(time);
          if (Number.isNaN(at.getTime())) return '-';
          const diffMins = Math.floor((now - at) / 60000);
          return `${diffMins}分钟`;
        },
        toggleIncidentSelect(incidentId) {
          const key = this.incidentIdKey(incidentId);
          const idx = this.selectedIncidents.findIndex((id) => this.incidentIdKey(id) === key);
          if (idx > -1) {
            this.selectedIncidents.splice(idx, 1);
          } else {
            this.selectedIncidents.push(key);
          }
        },
        incidentIdKey(incidentId) {
          return String(incidentId);
        },
        toggleSelectAllIncidents() {
          const visibleIds = this.incidents.map((incident) => this.incidentIdKey(incident.id));
          if (!visibleIds.length) return;

          if (this.allVisibleIncidentsSelected) {
            const visibleSet = new Set(visibleIds);
            this.selectedIncidents = this.selectedIncidents.filter((id) => !visibleSet.has(this.incidentIdKey(id)));
            return;
          }

          const merged = new Set(this.selectedIncidents.map((id) => this.incidentIdKey(id)));
          for (const id of visibleIds) {
            merged.add(id);
          }
          this.selectedIncidents = Array.from(merged);
        },
        clearIncidentSelection() {
          this.selectedIncidents = [];
        },
        async batchAckSelected() {
          for (const id of this.selectedIncidents) {
            try {
              await axios.post(`/incidents/${id}/ack`, {
                user_id: this.currentUser?.id || this.currentOncall?.user?.id || null,
                note: '批量操作：已认领',
              });
            } catch (error) {
              console.error(`ack ${id} failed:`, error);
            }
          }
          this.selectedIncidents = [];
          await this.loadAlertData(true);
        },
        async batchResolveSelected() {
          for (const id of this.selectedIncidents) {
            try {
              await axios.post(`/incidents/${id}/resolve`, {
                user_id: this.currentUser?.id || this.currentOncall?.user?.id || null,
                note: '批量操作：已关闭',
              });
            } catch (error) {
              console.error(`resolve ${id} failed:`, error);
            }
          }
          this.selectedIncidents = [];
          await this.loadAlertData(true);
        },
        getActionMilestone(action) {
          const milestoneMap = {
            'created': '创建',
            'notified': '通知',
            'acknowledged': '认领',
            'resolved': '关闭',
            'auto_resolved': '自动关闭',
            'deduplicated': '去重',
          };
          return milestoneMap[action] || null;
        },
        getTimelineItemClass(item) {
          if (item.key.startsWith('event-')) {
            const status = item.eventStatus || '';
            if (status === 'resolved' || status === 'recovered') {
              return 'bg-emerald-50 border-emerald-200';
            }
            return 'bg-rose-50 border-rose-200';
          }
          if (item.key.startsWith('log-')) {
            return 'bg-blue-50 border-blue-200';
          }
          return 'bg-amber-50 border-amber-200';
        },
        getTimelineMilestoneClass(item) {
          if (item.milestoneType === 'recovered') {
            return 'bg-emerald-100 text-emerald-700';
          }
          if (item.milestoneType === 'triggered') {
            return 'bg-rose-100 text-rose-700';
          }
          return 'bg-yellow-100 text-yellow-700';
        },
        async ensureMonthGenerated(scheduleId, year, month) {
          // month: 0-based (0=Jan) from JS Date
          if (!scheduleId) return;
          const start = new Date(year, month, 1);
          const end = new Date(year, month + 1, 0);
          const fmt = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
          try {
            await axios.post(`${API_BASE}/schedules/${scheduleId}/generate`, {
              start_date: fmt(start),
              end_date: fmt(end),
              include_secondary: true,
              regenerate: false,
            });
          } catch (e) {
            console.error('auto-generate month shifts failed', e);
            // 静默失败，避免影响页面体验
          }
        },
        async loadScheduleCalendar() {
          if (!this.selectedScheduleId) return;
          const year = this.monthDate.getFullYear();
          const month = this.monthDate.getMonth();
          await this.ensureMonthGenerated(this.selectedScheduleId, year, month);
          const { start, end } = this.monthRange;
          const startDate = `${start}T00:00:00`;
          const endDate = `${end}T23:59:59`;
          const res = await axios.get(`${API_BASE}/schedules/${this.selectedScheduleId}/calendar`, {
            params: { start_date: startDate, end_date: endDate },
          });
          this.normalShifts = res.data || [];
        },
        changeMonth(delta) {
          const d = new Date(this.monthDate.getFullYear(), this.monthDate.getMonth() + delta, 1);
          this.monthDate = d;
          if (this.activeTab === 'calendar' && this.selectedScheduleId) {
            this.loadScheduleCalendar();
          }
        },
      },
      mounted() {
        this.setupAxiosInterceptors();
        this.loadServerTimeMeta().finally(() => this.initializeAuth().then(async () => {
          if (this.currentUser) {
            await this.reloadAll();
            await this.applyDeepLink();
          }
        }).catch((error) => {
          alert(error.response?.data?.detail || error.message);
        }));

        setInterval(() => {
          this.refreshCountdown--;
          if (this.refreshCountdown <= 0) {
            this.refreshCountdown = 30;
            if (this.currentUser && this.activeFeature === 'alerts' && (this.selectedScheduleId || this.currentUser || this.alertScope !== 'mine')) {
              this.loadAlertData(true).catch(e => console.error('auto-refresh failed:', e));
            }
          }
        }, 1000);
      }
    }).mount('#app');
