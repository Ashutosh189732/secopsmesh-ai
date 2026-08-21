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

export function actorTypeClasses(type) {
  const key = (type || "").toLowerCase();
  const map = {
    user: "bg-blue-100 text-blue-800 border-blue-300",
    service: "bg-purple-100 text-purple-800 border-purple-300",
    system: "bg-gray-100 text-gray-700 border-gray-300",
    anonymous: "bg-red-100 text-red-800 border-red-300",
    other: "bg-gray-100 text-gray-600 border-gray-200",
  };
  return map[key] || "bg-gray-100 text-gray-600 border-gray-200";
}

export function actionClasses(action) {
  const key = (action || "").toLowerCase();
  const map = {
    create: "bg-green-100 text-green-800 border-green-300",
    read: "bg-blue-100 text-blue-800 border-blue-300",
    update: "bg-yellow-100 text-yellow-800 border-yellow-300",
    delete: "bg-red-100 text-red-800 border-red-300",
    execute: "bg-purple-100 text-purple-800 border-purple-300",
    access: "bg-cyan-100 text-cyan-800 border-cyan-300",
    other: "bg-gray-100 text-gray-700 border-gray-300",
  };
  return map[key] || "bg-gray-100 text-gray-700 border-gray-300";
}

export function outcomeClasses(outcome) {
  const key = (outcome || "").toLowerCase();
  const map = {
    success: "bg-emerald-100 text-emerald-800 border-emerald-400",
    failure: "bg-amber-100 text-amber-800 border-amber-400",
    blocked: "bg-red-100 text-red-800 border-red-400",
    partial: "bg-yellow-100 text-yellow-800 border-yellow-400",
  };
  return map[key] || "bg-gray-100 text-gray-700 border-gray-300";
}

export function actorIcon(type) {
  const key = (type || "").toLowerCase();
  const map = {
    user: "👤",
    service: "⚙️",
    system: "🖥️",
    anonymous: "❓",
    other: "🔹",
  };
  return map[key] || "🔹";
}

export function outcomeIcon(outcome) {
  const key = (outcome || "").toLowerCase();
  const map = {
    success: "✓",
    failure: "⚠",
    blocked: "🚫",
    partial: "◐",
  };
  return map[key] || "";
}

export function severityDotClasses(severity) {
  const key = (severity || "").toLowerCase();
  const map = {
    critical: "h-6 w-6 bg-red-500",
    high: "h-5 w-5 bg-orange-500",
    medium: "h-4 w-4 bg-yellow-500",
    low: "h-3 w-3 bg-gray-400",
  };
  return map[key] || "h-3 w-3 bg-gray-400";
}
