import { Body, Controller, Post } from '@nestjs/common';
import { ParseVisitTextDto } from './voice.dto';
import { VoiceVisitParserService } from './voice-visit-parser.service';

@Controller('voice')
export class VoiceController {
  constructor(private readonly parser: VoiceVisitParserService) {}

  @Post('parse-visit-text')
  parseVisitText(@Body() dto: ParseVisitTextDto) {
    return this.parser.parseVisitText(dto);
  }
}
