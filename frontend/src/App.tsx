import { useState, useEffect } from "react";
import {
  BrowserRouter,
  Routes,
  Route,
  Navigate,
  useNavigate,
  useLocation,
  NavLink,
} from "react-router-dom";
import { ThemeProvider, useTheme } from "next-themes";
import { Toaster } from "sonner";
import { Button } from "@/ui/button";
import {
  Car,
  LogOut,
  Settings,
  Sun,
  Moon,
  Home,
  BarChart3,
  Bot,
  ShieldCheck,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { clearAllChatData } from "@/utils/chatStorage";
import LoginPage from "./pages/LoginPage";
import TrafficDashboard from "@/modules/features/traffic/components/TrafficDashboard";
import AnalyticsPage from "./pages/AnalyticsPage";
import ChatPage from "./pages/ChatPage";
import ProfilePage from "./pages/ProfilePage";
import ProtectedRoute from "@/modules/features/auth/guards/ProtectedRoute";
import AdminResourcesPage from "@/pages/AdminResourcesPage";
import AdminRoadsPage from "@/pages/AdminRoadsPage";
import { authConfig } from "@/config";
import "./App.css";
import { TrafficProvider } from "@/hooks/useTrafficStore";

type NavItem = {
  to: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
};

const navItems: NavItem[] = [
  { to: "/home", label: "Trang Chủ", icon: Home },
  { to: "/analys", label: "Phân Tích", icon: BarChart3 },
  { to: "/chat", label: "Trợ Lý AI", icon: Bot },
];

export default function App() {
  return (
    <ThemeProvider attribute="class" defaultTheme="dark" enableSystem>
      <BrowserRouter>
        <AppContent />
      </BrowserRouter>
    </ThemeProvider>
  );
}

function AppContent() {
  const [showRegister, setShowRegister] = useState(false);
  const [authed, setAuthed] = useState(() => {
    const token = localStorage.getItem("access_token");
    if (token && token.length < 10) {
      localStorage.removeItem("access_token");
      return false;
    }
    return !!token;
  });
  const [isAdmin, setIsAdmin] = useState<boolean>(false);
  const [collapsed, setCollapsed] = useState(false);
  const { theme, setTheme } = useTheme();
  const location = useLocation();
  const isLoginPage = location.pathname === "/login";
  const isChatPage = location.pathname === "/chat";
  const navigate = useNavigate();

  const handleLoginSuccess = () => setAuthed(true);
  const handleRegisterSuccess = () => setShowRegister(false);
  const handleLogout = () => {
    localStorage.removeItem("access_token");
    clearAllChatData();
    setAuthed(false);
    setIsAdmin(false);
    navigate("/login", { replace: true });
  };

  useEffect(() => {
    const fetchMe = async () => {
      try {
        if (!authed) { setIsAdmin(false); return; }
        const token = localStorage.getItem("access_token");
        if (!token) { setIsAdmin(false); return; }
        const res = await fetch(`${authConfig.ME_URL}`, {
          headers: { Authorization: `Bearer ${token}` },
          credentials: "include",
        });
        if (!res.ok) { setIsAdmin(false); return; }
        const data = await res.json();
        setIsAdmin(data?.role_id === 0);
      } catch { setIsAdmin(false); }
    };
    fetchMe();
  }, [authed]);

  if (isLoginPage) {
    return (
      <div className="app-shell--login">
        <div className="login-theme-toggle">
          <Button
            variant="outline"
            size="icon"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            className="app-theme-toggle"
          >
            {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>
        </div>
        <TrafficProvider>
          <Routes>
            <Route
              path="/login"
              element={
                <LoginPage
                  onLoginSuccess={handleLoginSuccess}
                  onRegisterSuccess={handleRegisterSuccess}
                  showRegister={showRegister}
                  setShowRegister={setShowRegister}
                />
              }
            />
            <Route path="*" element={<Navigate to="/login" replace />} />
          </Routes>
        </TrafficProvider>
        <Toaster position="top-right" richColors />
      </div>
    );
  }

  return (
    <div className="sidebar-shell">
      {/* ── Sidebar ── */}
      <aside className={`sidebar ${collapsed ? "sidebar--collapsed" : ""}`}>
        {/* Brand */}
        <div className="sidebar-brand">
          <div className="sidebar-logo">
            <Car className="h-5 w-5" />
          </div>
          {!collapsed && (
            <div className="sidebar-brand-copy">
              <strong>Smart Traffic</strong>
              <small>Monitoring System</small>
            </div>
          )}
        </div>

        {/* Nav */}
        <nav className="sidebar-nav">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                title={collapsed ? item.label : undefined}
                className={({ isActive }) =>
                  `sidebar-nav-link ${isActive ? "sidebar-nav-link--active" : ""}`
                }
              >
                <Icon className="h-5 w-5 shrink-0" />
                {!collapsed && <span>{item.label}</span>}
              </NavLink>
            );
          })}

          {isAdmin && (
            <NavLink
              to="/admin/resources"
              title={collapsed ? "Trang Admin" : undefined}
              className={({ isActive }) =>
                `sidebar-nav-link sidebar-nav-link--admin ${isActive ? "sidebar-nav-link--active" : ""}`
              }
            >
              <ShieldCheck className="h-5 w-5 shrink-0" />
              {!collapsed && <span>Trang Admin</span>}
            </NavLink>
          )}
        </nav>

        {/* Bottom actions */}
        <div className="sidebar-bottom">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            className="sidebar-icon-btn"
            title={theme === "dark" ? "Chế độ sáng" : "Chế độ tối"}
          >
            {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>

          <NavLink
            to="/profile"
            title={collapsed ? "Tài khoản" : undefined}
            className={({ isActive }) =>
              `sidebar-icon-btn ${isActive ? "sidebar-icon-btn--active" : ""}`
            }
          >
            <Settings className="h-4 w-4" />
            {!collapsed && <span className="text-sm font-medium">Tài khoản</span>}
          </NavLink>

          <button
            className="sidebar-icon-btn sidebar-icon-btn--danger"
            onClick={handleLogout}
            title="Đăng xuất"
            type="button"
          >
            <LogOut className="h-4 w-4" />
            {!collapsed && <span className="text-sm font-medium">Đăng xuất</span>}
          </button>

          {/* Collapse toggle */}
          <button
            className="sidebar-collapse-btn"
            onClick={() => setCollapsed((v) => !v)}
            title={collapsed ? "Mở rộng" : "Thu gọn"}
            type="button"
          >
            {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
          </button>
        </div>
      </aside>

      {/* ── Main content ── */}
      <div className={`sidebar-content ${isChatPage ? "sidebar-content--chat" : ""}`}>
        <TrafficProvider>
          <Routes>
            <Route element={<ProtectedRoute />}>
              <Route path="/home" element={<TrafficDashboard />} />
              <Route path="/analys" element={<AnalyticsPage />} />
              <Route path="/chat" element={<ChatPage />} />
              <Route path="/profile" element={<ProfilePage />} />
              <Route path="/admin" element={<Navigate to="/admin/resources" replace />} />
              <Route path="/admin/resources" element={<AdminResourcesPage />} />
              <Route path="/admin/roads" element={<AdminRoadsPage />} />
            </Route>
            <Route path="*" element={<Navigate to={authed ? "/home" : "/login"} replace />} />
          </Routes>
        </TrafficProvider>
      </div>

      <Toaster position="top-right" richColors />
    </div>
  );
}
