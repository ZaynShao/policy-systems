// 独立版外壳:原平台的 AiModule 是同事写的,这里只是让我的模块能照原样 import。
import { Module } from '@nestjs/common';
import { DeepseekService } from './deepseek.service';

@Module({
  providers: [DeepseekService],
  exports: [DeepseekService],
})
export class AiModule {}
