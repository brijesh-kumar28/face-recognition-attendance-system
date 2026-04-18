"use client";

import { useEffect, useState, useCallback } from "react";
import { DataTable, type Column } from "@/components/DataTable";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useToast } from "@/components/ui/use-toast";
import { Trash2, RefreshCw, Search, UserPlus, Eye, EyeOff, Copy, Pencil } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import api from "@/lib/axios";
import type { User } from "@/lib/types";

export default function ManageUsersPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [deleteUser, setDeleteUser] = useState<User | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [editUser, setEditUser] = useState<User | null>(null);
  const [editName, setEditName] = useState("");
  const [editEmail, setEditEmail] = useState("");
  const [editDepartment, setEditDepartment] = useState("");
  const [editPassword, setEditPassword] = useState("");
  const [isUpdating, setIsUpdating] = useState(false);
  const { toast } = useToast();

  // Register user state
  const [showRegister, setShowRegister] = useState(false);
  const [regName, setRegName] = useState("");
  const [regEmail, setRegEmail] = useState("");
  const [regPassword, setRegPassword] = useState("");
  const [regDepartment, setRegDepartment] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [isRegistering, setIsRegistering] = useState(false);
  const [registeredCreds, setRegisteredCreds] = useState<{ email: string; password: string } | null>(null);

  const fetchUsers = useCallback(async () => {
    try {
      setIsLoading(true);
      const res = await api.get("/api/admin/users");
      setUsers(res.data.items ?? res.data);
    } catch {
      toast({
        title: "Error",
        description: "Failed to fetch users",
        variant: "destructive",
      });
    } finally {
      setIsLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  const handleRegister = async () => {
    if (!regName || !regEmail || !regPassword) {
      toast({ title: "Error", description: "Name, email and password are required", variant: "destructive" });
      return;
    }
    if (regPassword.length < 6) {
      toast({ title: "Error", description: "Password must be at least 6 characters", variant: "destructive" });
      return;
    }
    setIsRegistering(true);
    try {
      await api.post("/api/admin/register-user", {
        name: regName,
        email: regEmail,
        password: regPassword,
        department: regDepartment,
      });
      toast({ title: "User registered", description: `${regName} has been registered successfully.` });
      setRegisteredCreds({ email: regEmail, password: regPassword });
      fetchUsers();
    } catch (error: unknown) {
      const err = error as { response?: { data?: { error?: string } } };
      toast({
        title: "Registration failed",
        description: err?.response?.data?.error || "Failed to register user",
        variant: "destructive",
      });
    } finally {
      setIsRegistering(false);
    }
  };

  const resetRegisterForm = () => {
    setRegName("");
    setRegEmail("");
    setRegPassword("");
    setRegDepartment("");
    setShowPassword(false);
    setRegisteredCreds(null);
  };

  const handleDelete = async () => {
    if (!deleteUser) return;
    setIsDeleting(true);
    try {
      await api.delete(`/api/admin/users/${deleteUser.id}`);
      setUsers((prev) => prev.filter((u) => u.id !== deleteUser.id));
      toast({ title: "User deleted", description: `${deleteUser.name} has been removed.` });
      setDeleteUser(null);
    } catch (error: unknown) {
      const err = error as { response?: { data?: { error?: string } } };
      toast({
        title: "Error",
        description: err?.response?.data?.error || "Failed to delete user",
        variant: "destructive",
      });
    } finally {
      setIsDeleting(false);
    }
  };

  const openEditDialog = (user: User) => {
    setEditUser(user);
    setEditName(user.name || "");
    setEditEmail(user.email || "");
    setEditDepartment(user.department || "");
    setEditPassword("");
  };

  const closeEditDialog = () => {
    setEditUser(null);
    setEditName("");
    setEditEmail("");
    setEditDepartment("");
    setEditPassword("");
    setIsUpdating(false);
  };

  const handleUpdate = async () => {
    if (!editUser) return;
    if (!editName.trim() || !editEmail.trim()) {
      toast({
        title: "Error",
        description: "Name and email are required",
        variant: "destructive",
      });
      return;
    }

    if (editPassword && editPassword.length < 6) {
      toast({
        title: "Error",
        description: "Password must be at least 6 characters",
        variant: "destructive",
      });
      return;
    }

    setIsUpdating(true);
    try {
      const res = await api.put(`/api/admin/users/${editUser.id}`, {
        name: editName.trim(),
        email: editEmail.trim(),
        department: editDepartment.trim(),
        password: editPassword,
      });

      const updated: User = res.data?.user;
      if (updated) {
        setUsers((prev) => prev.map((u) => (u.id === updated.id ? updated : u)));
      } else {
        fetchUsers();
      }

      toast({
        title: "User updated",
        description: res?.data?.warning || `${editName.trim()} has been updated successfully.`,
      });
      closeEditDialog();
    } catch (error: unknown) {
      const err = error as { response?: { data?: { error?: string } } };
      toast({
        title: "Update failed",
        description: err?.response?.data?.error || "Failed to update user",
        variant: "destructive",
      });
    } finally {
      setIsUpdating(false);
    }
  };

  const handleRetrain = async (userId: string) => {
    try {
      await api.post(`/api/admin/train`, { userId });
      toast({ title: "Retrain initiated", description: "Model retraining started." });
      fetchUsers();
    } catch (error: unknown) {
      const err = error as { response?: { data?: { error?: string } } };
      toast({
        title: "Error",
        description: err?.response?.data?.error || "Failed to initiate retrain",
        variant: "destructive",
      });
    }
  };

  const filteredUsers = users.filter(
    (u) =>
      u.name.toLowerCase().includes(search.toLowerCase()) ||
      u.email.toLowerCase().includes(search.toLowerCase()) ||
      (u.department?.toLowerCase().includes(search.toLowerCase()) ?? false)
  );

  const columns: Column<User>[] = [
    { key: "name", header: "Name" },
    { key: "email", header: "Email" },
    { key: "department", header: "Department" },
    {
      key: "trainingStatus",
      header: "Training Status",
      render: (user) => (
        <Badge
          variant={
            user.trainingStatus === "trained"
              ? "success"
              : user.trainingStatus === "pending"
              ? "warning"
              : "secondary"
          }
        >
          {user.trainingStatus || "untrained"}
        </Badge>
      ),
    },
    {
      key: "actions",
      header: "Actions",
      render: (user) => (
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => openEditDialog(user)}
            title="Edit"
          >
            <Pencil className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => handleRetrain(user.id)}
            title="Retrain"
          >
            <RefreshCw className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setDeleteUser(user)}
            className="text-destructive hover:text-destructive"
            title="Delete"
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Manage Users</h1>
        <p className="text-muted-foreground">
          Register, view and manage users
        </p>
      </div>

      <div className="flex items-center gap-4">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search users..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-10"
          />
        </div>
        <Button variant="outline" onClick={fetchUsers}>
          <RefreshCw className="mr-2 h-4 w-4" />
          Refresh
        </Button>
        <Button onClick={() => { resetRegisterForm(); setShowRegister(true); }}>
          <UserPlus className="mr-2 h-4 w-4" />
          Register User
        </Button>
      </div>

      <DataTable
        columns={columns}
        data={filteredUsers}
        isLoading={isLoading}
        emptyMessage="No users found."
      />

      {/* Edit User Dialog */}
      <Dialog open={!!editUser} onOpenChange={(open) => { if (!open) closeEditDialog(); }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Edit User</DialogTitle>
            <DialogDescription>
              Update user profile details. Password is optional and only changed if provided.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="edit-name">Full Name *</Label>
              <Input
                id="edit-name"
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                disabled={isUpdating}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="edit-email">Email *</Label>
              <Input
                id="edit-email"
                type="email"
                value={editEmail}
                onChange={(e) => setEditEmail(e.target.value)}
                disabled={isUpdating}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="edit-department">Department</Label>
              <Input
                id="edit-department"
                value={editDepartment}
                onChange={(e) => setEditDepartment(e.target.value)}
                disabled={isUpdating}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="edit-password">New Password (optional)</Label>
              <Input
                id="edit-password"
                type="password"
                placeholder="Leave blank to keep current password"
                value={editPassword}
                onChange={(e) => setEditPassword(e.target.value)}
                disabled={isUpdating}
              />
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={closeEditDialog} disabled={isUpdating}>
              Cancel
            </Button>
            <Button onClick={handleUpdate} disabled={isUpdating}>
              {isUpdating ? "Saving..." : "Save Changes"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Register User Dialog */}
      <Dialog open={showRegister} onOpenChange={(open) => { if (!open) { setShowRegister(false); resetRegisterForm(); } }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Register New User</DialogTitle>
            <DialogDescription>
              {registeredCreds
                ? "User registered! Share these credentials with the user."
                : "Create a new user account. The user can login with these credentials to view their attendance reports."}
            </DialogDescription>
          </DialogHeader>

          {registeredCreds ? (
            <div className="space-y-4">
              <div className="rounded-lg border bg-muted/50 p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-xs text-muted-foreground">Email</p>
                    <p className="font-mono text-sm font-medium">{registeredCreds.email}</p>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => {
                      navigator.clipboard.writeText(registeredCreds.email);
                      toast({ title: "Copied!", description: "Email copied to clipboard" });
                    }}
                  >
                    <Copy className="h-4 w-4" />
                  </Button>
                </div>
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-xs text-muted-foreground">Password</p>
                    <p className="font-mono text-sm font-medium">{registeredCreds.password}</p>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => {
                      navigator.clipboard.writeText(registeredCreds.password);
                      toast({ title: "Copied!", description: "Password copied to clipboard" });
                    }}
                  >
                    <Copy className="h-4 w-4" />
                  </Button>
                </div>
              </div>
              <DialogFooter>
                <Button onClick={() => { setShowRegister(false); resetRegisterForm(); }}>
                  Done
                </Button>
              </DialogFooter>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="reg-name">Full Name *</Label>
                <Input
                  id="reg-name"
                  placeholder="John Doe"
                  value={regName}
                  onChange={(e) => setRegName(e.target.value)}
                  disabled={isRegistering}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="reg-email">Email *</Label>
                <Input
                  id="reg-email"
                  type="email"
                  placeholder="john@example.com"
                  value={regEmail}
                  onChange={(e) => setRegEmail(e.target.value)}
                  disabled={isRegistering}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="reg-department">Department</Label>
                <Input
                  id="reg-department"
                  placeholder="Engineering"
                  value={regDepartment}
                  onChange={(e) => setRegDepartment(e.target.value)}
                  disabled={isRegistering}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="reg-password">Password *</Label>
                <div className="relative">
                  <Input
                    id="reg-password"
                    type={showPassword ? "text" : "password"}
                    placeholder="Min 6 characters"
                    value={regPassword}
                    onChange={(e) => setRegPassword(e.target.value)}
                    disabled={isRegistering}
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="absolute right-0 top-0 h-10 w-10 hover:bg-transparent"
                    onClick={() => setShowPassword(!showPassword)}
                  >
                    {showPassword ? (
                      <EyeOff className="h-4 w-4 text-muted-foreground" />
                    ) : (
                      <Eye className="h-4 w-4 text-muted-foreground" />
                    )}
                  </Button>
                </div>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => { setShowRegister(false); resetRegisterForm(); }}>
                  Cancel
                </Button>
                <Button onClick={handleRegister} disabled={isRegistering}>
                  {isRegistering ? "Registering..." : "Register User"}
                </Button>
              </DialogFooter>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog open={!!deleteUser} onOpenChange={() => setDeleteUser(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete User</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete{" "}
              <span className="font-semibold">{deleteUser?.name}</span>? This
              action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteUser(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={isDeleting}
            >
              {isDeleting ? "Deleting..." : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
