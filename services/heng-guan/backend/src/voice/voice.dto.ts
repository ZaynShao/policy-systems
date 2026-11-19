import { IsOptional, IsString, MinLength } from 'class-validator';

export class ParseVisitTextDto {
  @IsString()
  @MinLength(2)
  transcript!: string;

  @IsOptional()
  context?: {
    today?: string;
    currentRegion?: string | null;
    currentOrgName?: string | null;
  };
}

export interface ParsedVisitFields {
  region: string | null;
  orgName: string | null;
  contactName: string | null;
  contactDepart: string | null;
  contactPhone: string | null;
  topic: string | null;
  goal: string | null;
  plannedAt: string | null;
}

export interface ParseVisitTextResponse {
  transcript: string;
  parsed: ParsedVisitFields;
}
