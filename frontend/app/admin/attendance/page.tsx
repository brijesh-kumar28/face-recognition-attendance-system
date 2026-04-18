"use client";

import { useEffect, useState, useCallback } from "react";
import { DataTable, type Column } from "@/components/DataTable";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/components/ui/use-toast";
import { Search, Download, CalendarIcon } from "lucide-react";
import api from "@/lib/axios";
import type { AttendanceRecord } from "@/lib/types";

export default function AdminAttendancePage() {
  const [records, setRecords] = useState<AttendanceRecord[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [dateFilter, setDateFilter] = useState("");
  const [userFilter, setUserFilter] = useState("");
  const [departmentFilter, setDepartmentFilter] = useState("all");
  const { toast } = useToast();

  const fetchAttendance = useCallback(async () => {
    try {
      setIsLoading(true);
      const params: Record<string, string> = {};
      if (dateFilter) params.date = dateFilter;
      if (userFilter) params.user = userFilter;
      if (departmentFilter && departmentFilter !== "all")
        params.department = departmentFilter;

      const res = await api.get("/api/admin/attendance", { params });
      setRecords(res.data.items ?? res.data);
    } catch {
      toast({
        title: "Error",
        description: "Failed to fetch attendance records",
        variant: "destructive",
      });
    } finally {
      setIsLoading(false);
    }
  }, [dateFilter, userFilter, departmentFilter, toast]);

  useEffect(() => {
    fetchAttendance();
  }, [fetchAttendance]);

  const handleExportCSV = () => {
    if (records.length === 0) {
      toast({
        title: "No data",
        description: "No records to export",
        variant: "destructive",
      });
      return;
    }

    const headers = ["Name", "Date", "Check In", "Check Out", "Status", "Department"];
    const csvData = records.map((r) =>
      [r.userName, r.date, r.checkIn, r.checkOut || "-", r.status, r.department || "-"].join(",")
    );
    const csv = [headers.join(","), ...csvData].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `attendance_${new Date().toISOString().split("T")[0]}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    toast({ title: "Exported", description: "CSV file downloaded" });
  };

  const columns: Column<AttendanceRecord>[] = [
    { key: "userName", header: "Name" },
    { key: "date", header: "Date" },
    { key: "checkIn", header: "Check In" },
    {
      key: "checkOut",
      header: "Check Out",
      render: (r) => <span>{r.checkOut || "—"}</span>,
    },
    {
      key: "status",
      header: "Status",
      render: (r) => (
        <Badge
          variant={
            r.status === "present"
              ? "success"
              : r.status === "late"
              ? "warning"
              : "destructive"
          }
        >
          {r.status}
        </Badge>
      ),
    },
    { key: "department", header: "Department" },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">
            Attendance Records
          </h1>
          <p className="text-muted-foreground">
            View and filter all attendance records
          </p>
        </div>
        <Button onClick={handleExportCSV} variant="outline">
          <Download className="mr-2 h-4 w-4" />
          Export CSV
        </Button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-4">
        <div className="relative">
          <CalendarIcon className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            type="date"
            value={dateFilter}
            onChange={(e) => setDateFilter(e.target.value)}
            className="pl-10 w-[180px]"
          />
        </div>
        <div className="relative">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Filter by user..."
            value={userFilter}
            onChange={(e) => setUserFilter(e.target.value)}
            className="pl-10 w-[200px]"
          />
        </div>
        <Select value={departmentFilter} onValueChange={setDepartmentFilter}>
          <SelectTrigger className="w-[180px]">
            <SelectValue placeholder="Department" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Departments</SelectItem>
            <SelectItem value="engineering">Engineering</SelectItem>
            <SelectItem value="hr">HR</SelectItem>
            <SelectItem value="marketing">Marketing</SelectItem>
            <SelectItem value="finance">Finance</SelectItem>
          </SelectContent>
        </Select>
        <Button
          variant="ghost"
          onClick={() => {
            setDateFilter("");
            setUserFilter("");
            setDepartmentFilter("all");
          }}
        >
          Clear Filters
        </Button>
      </div>

      <DataTable
        columns={columns}
        data={records}
        isLoading={isLoading}
        emptyMessage="No attendance records found."
      />
    </div>
  );
}
