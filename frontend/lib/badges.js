export function severityClasses(severity) {
  const key = (severity || "").toLowerCase();
  const map = {
    critical: "bg-red-100 text-red-800 border-red-300",
    high: "bg-orange-100 text-orange-800 border-orange-300",
    medium: "bg-yellow-100 text-yellow-800 border-yellow-300",
    low: "bg-gray-100 text-gray-700 border-gray-300",
  };
  return map[key] || "bg-gray-100 text-gray-700 border-gray-300";
}

export function statusClasses(status) {
  const key = (status || "").toLowerCase();
  const map = {
    parked: "bg-gray-100 text-gray-600 border-gray-300",
    queued: "bg-blue-100 text-blue-800 border-blue-300",
    investigating: "bg-amber-100 text-amber-800 border-amber-300",
    complete: "bg-green-100 text-green-800 border-green-300",
  };
  return map[key] || "bg-gray-100 text-gray-700 border-gray-300";
}

export function priorityClasses(priority) {
  const key = (priority || "").toLowerCase();
  const map = {
    high: "bg-red-100 text-red-800 border-red-300",
    medium: "bg-yellow-100 text-yellow-800 border-yellow-300",
    low: "bg-gray-100 text-gray-700 border-gray-300",
  };
  return map[key] || "bg-gray-100 text-gray-700 border-gray-300";
}
