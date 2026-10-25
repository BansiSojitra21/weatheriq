export type Location = {
  id: number;
  name: string;
  country: string;
  latitude: number;
  longitude: number;
  timezone: string;
  elevation_m: number | null;
  is_default: boolean;
};

export type AlertItem = {
  id: number;
  location_id: number;
  location_name?: string | null;
  alert_type: string;
  severity: string;
  title: string;
  message: string;
  variable: string;
  threshold: number | null;
  actual_value: number | null;
  event_time: string;
  status: string;
  source: string;
  condition_kind: string;
  delivery: {
    state: string;
    channel: string | null;
    destination: string | null;
    attempted_at: string | null;
    attempts: number;
  };
};

export type AnomalyItem = {
  id: number;
  location_id: number;
  location_name?: string | null;
  variable: string;
  observed_at: string;
  observed_value: number;
  expected_low: number | null;
  expected_high: number | null;
  score: number | null;
  method: string;
  explanation: string;
  review_status: string;
  is_hazard_warning: boolean;
};

