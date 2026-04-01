export interface Wahlkreis {
  nr: number;
  name: string;
  overlap: number;
}

export interface BundestagEntry {
  wahlkreise: Wahlkreis[];
  primary: number;
  period_id: number;
}

export interface LandtagEntry {
  state: string;
  wahlkreise: Wahlkreis[];
  primary: number;
  period_id: number;
}

export interface PlzResult {
  plz: string;
  bundestag: BundestagEntry | null;
  landtage: LandtagEntry[];
}
