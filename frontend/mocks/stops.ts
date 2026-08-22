import { StopRead } from "../types";

/**
 * Real transit stops in Islamabad & Rawalpindi with verified coordinates
 * Sourced from backend/docs/transit_data.json
 */
export const MOCK_STOPS: StopRead[] = [
  {
    id: "a1b2c3d4-0001-5000-8000-000000000001",
    name: "Pak Secretariat",
    location: { latitude: 33.7297, longitude: 73.0931 },
    distance_m: 1200,
  },
  {
    id: "a1b2c3d4-0001-5000-8000-000000000002",
    name: "Parade Ground",
    location: { latitude: 33.7194, longitude: 73.0768 },
    distance_m: 850,
  },
  {
    id: "a1b2c3d4-0001-5000-8000-000000000003",
    name: "PIMS",
    location: { latitude: 33.6938, longitude: 73.0544 },
    distance_m: 350,
  },
  {
    id: "a1b2c3d4-0001-5000-8000-000000000004",
    name: "Ibn-e-Sina",
    location: { latitude: 33.6844, longitude: 73.0479 },
    distance_m: 420,
  },
  {
    id: "a1b2c3d4-0001-5000-8000-000000000005",
    name: "Chaman",
    location: { latitude: 33.6761, longitude: 73.0412 },
    distance_m: 650,
  },
  {
    id: "a1b2c3d4-0001-5000-8000-000000000006",
    name: "Faiz Ahmed Faiz",
    location: { latitude: 33.6669, longitude: 73.0336 },
    distance_m: 900,
  },
  {
    id: "a1b2c3d4-0001-5000-8000-000000000007",
    name: "Faizabad",
    location: { latitude: 33.6631, longitude: 73.0825 },
    distance_m: 1100,
  },
  {
    id: "a1b2c3d4-0001-5000-8000-000000000008",
    name: "Shamsabad",
    location: { latitude: 33.6497, longitude: 73.0789 },
    distance_m: 1400,
  },
  {
    id: "a1b2c3d4-0001-5000-8000-000000000009",
    name: "Chandni Chowk",
    location: { latitude: 33.6339, longitude: 73.0733 },
    distance_m: 1800,
  },
  {
    id: "a1b2c3d4-0001-5000-8000-000000000010",
    name: "Saddar",
    location: { latitude: 33.5975, longitude: 73.0547 },
    distance_m: 2100,
  },
  {
    id: "a1b2c3d4-0001-5000-8000-000000000011",
    name: "Ammar Chowk",
    location: { latitude: 33.5850, longitude: 73.0760 },
    distance_m: 2500,
  },
  {
    id: "a1b2c3d4-0001-5000-8000-000000000012",
    name: "Bhara Kahu Terminal",
    location: { latitude: 33.7431, longitude: 73.1678 },
    distance_m: 3200,
  },
  {
    id: "a1b2c3d4-0001-5000-8000-000000000013",
    name: "NUST H-12 Gate 1",
    location: { latitude: 33.6467, longitude: 72.9906 },
    distance_m: 1750,
  },
  {
    id: "a1b2c3d4-0001-5000-8000-000000000014",
    name: "IIUI Gate 2",
    location: { latitude: 33.6589, longitude: 73.0189 },
    distance_m: 1300,
  },
];
