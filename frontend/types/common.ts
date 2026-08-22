export interface Location {
  latitude: number;
  longitude: number;
}

export type GeoCoordinates = [number, number]; // [longitude, latitude] per GeoJSON standard

export interface ApiErrorResponse {
  detail: string | Array<{ loc: (string | number)[]; msg: string; type: string }>;
}
