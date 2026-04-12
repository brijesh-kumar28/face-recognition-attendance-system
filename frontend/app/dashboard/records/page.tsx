"use client";

import { useEffect, useState, useCallback } from "react";
import { DataTable, type Column } from "@/components/DataTable";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { CalendarIcon } from "lucide-react";
import api from "@/lib/axios";
import type { AttendanceRecord } from "@/lib/types";

export default function MyRecordsPage() {
  const [records, setRecords] = useState<AttendanceRecord[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [dateFilter, setDateFilter] = useState("");

  const fetchRecords = useCallback(async () => {
    try {
      setIsLoading(true);
      const params: Record<string, string> = {};
      if (dateFilter) params.date = dateFilter;
      const res = await api.get("/api/user/attendance", { params });
      setRecords(res.data);
    } catch {
      // silent
    } finally {
      setIsLoading(false);
    }
  }, [dateFilter]);

  useEffect(() => {
    fetchRecords();
  }, [fetchRecords]);

  const columns: Column<AttendanceRecord>[] = [
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
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">My Records</h1>
        <p className="text-muted-foreground">Your attendance history</p>
      </div>

      <div className="flex items-center gap-4">
        <div className="relative">
          <CalendarIcon className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            type="date"
            value={dateFilter}
            onChange={(e) => setDateFilter(e.target.value)}
            className="pl-10 w-[180px]"
          />
        </div>
        {dateFilter && (
          <button
            onClick={() => setDateFilter("")}
            className="text-sm text-muted-foreground hover:text-foreground"
          >
            Clear filter
          </button>
        )}
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
