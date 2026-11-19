import { Body, Controller, Delete, Get, HttpCode, HttpStatus, Post, Put, Query, Req } from '@nestjs/common';
import { GovRiskService } from './gov-risk.service';

/** 所有者本人用:平台登录后从个人工作台页面调用。 */
@Controller('gov-risk')
export class GovRiskController {
  constructor(private readonly service: GovRiskService) {}

  @Get('package')
  getPackage(@Req() req: any) {
    return this.service.getPackage(req.user);
  }

  @Get('run')
  getRun(@Req() req: any) {
    return this.service.getRun(req.user);
  }

  @Post('runs')
  @HttpCode(HttpStatus.ACCEPTED)
  requestRun(@Req() req: any) {
    return this.service.requestRun(req.user);
  }

  @Get('cases')
  getCases(@Req() req: any, @Query('ids') ids: string) {
    return this.service.getCases(req.user, ids);
  }

  @Get('feedback')
  getFeedback(@Req() req: any) {
    return this.service.getFeedback(req.user);
  }

  @Put('feedback')
  putFeedback(@Req() req: any, @Body() body: unknown) {
    return this.service.putFeedback(req.user, body);
  }
}

/** 本地服务用:JwtAuthGuard 按 x-gov-risk-agent-token 校验,不走用户登录。 */
@Controller('internal/gov-risk')
export class GovRiskInternalController {
  constructor(private readonly service: GovRiskService) {}

  @Put('cases')
  uploadCases(@Body() body: unknown) {
    return this.service.uploadCases(body);
  }

  @Delete('cases')
  purge(@Body() body: unknown) {
    return this.service.purge(body);
  }

  @Get('run')
  getRun() {
    return this.service.getRun(undefined, true);
  }

  @Get('package')
  getPackage() {
    return this.service.getPackage(undefined, true);
  }
}
