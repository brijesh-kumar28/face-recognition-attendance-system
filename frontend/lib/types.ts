export interface User {
  id: string;
  name: string;
  email: string;
  role: "admin" | "user";
  department?: string;
  profileImage?: string;
  trainingStatus?: "trained" | "untrained" | "pending";
  createdAt?: string;
}

export interface AuthState {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  fetchUser: () => Promise<void>;
}

export interface RegisterData {
  name: string;
  email: string;
  password: string;
  department?: string;
}

export interface LoginResponse {
  token: string;
  user: User;
}

export interface AdminStats {
  totalUsers: number;
  trainedUsers: number;
  todayAttendance: number;
  totalRecords: number;
  weeklyTrend: WeeklyTrend[];
  userGrowth: UserGrowth[];
}

export interface UserStats {
  todayStatus: "present" | "absent" | "not_marked";
  totalPresent: number;
  totalAbsent: number;
  streak: number;
}

export interface WeeklyTrend {
  day: string;
  count: number;
}

export interface UserGrowth {
  month: string;
  users: number;
}

export interface AttendanceRecord {
  id: string;
  userId: string;
  userName: string;
  date: string;
  checkIn: string;
  checkOut?: string;
  status: "present" | "absent" | "late";
  department?: string;
}

export interface TrainingUser {
  id: string;
  name: string;
  email: string;
  department: string;
  images: number;
}

export interface ApiResponse<T> {
  success: boolean;
  data: T;
  message?: string;
}
