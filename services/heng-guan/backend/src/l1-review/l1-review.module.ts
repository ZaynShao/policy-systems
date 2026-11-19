import { Module } from '@nestjs/common';
import { AiModule } from '../ai/ai.module';
import { PrismaModule } from '../prisma/prisma.module';
import { L1ReviewController } from './l1-review.controller';
import { L1ReviewService } from './l1-review.service';

@Module({
  imports: [PrismaModule, AiModule],
  controllers: [L1ReviewController],
  providers: [L1ReviewService],
})
export class L1ReviewModule {}
