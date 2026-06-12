import { Module } from '@nestjs/common';
import { AiModule } from '../ai/ai.module';
import { VoiceController } from './voice.controller';
import { VoiceVisitParserService } from './voice-visit-parser.service';

@Module({
  imports: [AiModule],
  controllers: [VoiceController],
  providers: [VoiceVisitParserService],
})
export class VoiceModule {}
