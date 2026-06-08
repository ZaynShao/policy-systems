import { Controller, ForbiddenException, Get, Param, Patch, Query, Req, UseGuards } from '@nestjs/common';
import { JwtAuthGuard } from '../common/guards/jwt-auth.guard';
import { NotificationService } from './notification.service';

@UseGuards(JwtAuthGuard)
@Controller('notifications')
export class NotificationController {
  constructor(private svc: NotificationService) {}

  private assertManager(req: any) {
    if (req.user?.role !== 'MANAGER') throw new ForbiddenException('仅管理员可见');
  }

  @Get()
  list(@Req() req: any, @Query('unreadOnly') unreadOnly?: string, @Query('limit') limit?: string) {
    this.assertManager(req);
    return this.svc.list(req.user.role, req.user?.id, { unreadOnly: unreadOnly === 'true', limit: limit ? +limit : 50 });
  }

  @Patch(':id/read')
  read(@Req() req: any, @Param('id') id: string) {
    this.assertManager(req);
    return this.svc.markRead(id);
  }
}
