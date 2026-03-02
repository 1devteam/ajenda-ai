import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface AuthState {
  token: string | null;
  username: string | null;
  isAuthenticated: boolean;
  setAuth: (token: string, username: string) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      username: null,
      isAuthenticated: false,
      setAuth: (token, username) => {
        localStorage.setItem('omnipath_token', token);
        set({ token, username, isAuthenticated: true });
      },
      logout: () => {
        localStorage.removeItem('omnipath_token');
        set({ token: null, username: null, isAuthenticated: false });
      },
    }),
    { name: 'omnipath-auth' }
  )
);

interface UIState {
  sidebarCollapsed: boolean;
  activePage: string;
  toggleSidebar: () => void;
  setActivePage: (page: string) => void;
}

export const useUIStore = create<UIState>((set) => ({
  sidebarCollapsed: false,
  activePage: 'overview',
  toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
  setActivePage: (page) => set({ activePage: page }),
}));
