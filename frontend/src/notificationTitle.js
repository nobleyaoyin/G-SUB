import {workflowStatusLabel} from './workflowStatus';
export function notificationTitle(value) {
  if (typeof value !== 'string' || !value.trim()) return 'Notification';
  return workflowStatusLabel(value);
}
