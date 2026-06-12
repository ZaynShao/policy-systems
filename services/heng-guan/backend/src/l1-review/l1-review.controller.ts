import { Body, Controller, ForbiddenException, Get, Param, Patch, Post, Query, Req, UseGuards } from '@nestjs/common';
import { JwtAuthGuard } from '../common/guards/jwt-auth.guard';
import { L1ReviewService } from './l1-review.service';

@UseGuards(JwtAuthGuard)
@Controller('l1-review')
export class L1ReviewController {
  constructor(private svc: L1ReviewService) {}

  private assertManager(req: any) {
    // HENG_L1_REVIEW_ACCOUNTS: 账号级豁免(平台登录名,逗号分隔),不改全局 role
    const allow = (process.env.HENG_L1_REVIEW_ACCOUNTS || '')
      .split(',').map((s: string) => s.trim()).filter(Boolean);
    if (req.user?.role !== 'MANAGER' && !allow.includes(req.user?.id)) {
      throw new ForbiddenException('仅管理员可见');
    }
  }

  @Get()
  list(@Req() req: any, @Query('kind') kind?: string, @Query('pending') pending?: string) {
    this.assertManager(req);
    return this.svc.list(kind, pending !== 'false');
  }

  @Post(':id/narrate')
  narrate(@Req() req: any, @Param('id') id: string) {
    this.assertManager(req);
    return this.svc.narrate(id);
  }

  @Patch(':id/verdict')
  verdict(@Req() req: any, @Param('id') id: string, @Body() body: any) {
    this.assertManager(req);
    return this.svc.submitVerdict(id, body, req.user);
  }
}
