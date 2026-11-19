// @ts-nocheck —— 片段文件:不进编译、不必能运行(说明见下)。
//
// 月刊后端里我写的几段(原项目 PR 1185,原样照搬)。
// 原平台的月刊后端(monthly.service.ts、monthly.controller.ts)和接口契约(contracts/heng-backend.openapi.json)
// 是同事建的,不在本仓。我在里面加了「人工修改意见」的记录接口:读者在月刊详情页提交意见 → 存进
// content.pendingNote,由产线下一轮回炉时消费(services/policy-pipeline/scripts/l3_monthly/human_note.py)。
//
// 下面按原文件分成四段。包住片段的 class / const 和带「外壳」字样的行是为了让片段有个地方放,
// 同事写的其余部分一行不带;依赖的 Nest、Prisma 和月刊模块本身都不在本仓,所以单独跑不起来。
// 离线演示页面的接口替身(frontend/src/standalone/monthly/mock.ts)按这里的规则回答。

// ── 片段一:原 monthly.service.ts 第 1 行(这行引入是同事的,我加了 BadRequestException) ──
import { BadRequestException, Injectable, Logger, NotFoundException } from '@nestjs/common';
// 外壳:片段三要用的装饰器(原 controller 文件里的引入是同事写的)
import { Body, Param, Post } from '@nestjs/common';

// ── 片段二:原 monthly.service.ts 的 MonthlyService 类里我加的方法 ──
class MonthlyService { // 外壳
  /**
   * 记录人工修改意见,等产线下一轮回炉。
   *
   * 意见存进 content.pendingNote —— content 是 Json 列,**不需要建表也不需要迁移**。
   * 这里**不直接改稿**:改稿要连同原文与该段素材包一起重写并重过 F 门,
   * 素材包在 policy-pipeline 那边;这边直接改就是又开一条绕过事实核查的口子。
   * 产线消费掉这条意见后,会落一行 MonthlyVersion 把意见原文记进 changeNote。
   */
  async submitRevisionNote(monthlyId: string, note: string) {
    const text = (note ?? '').trim();
    if (!text) throw new BadRequestException('修改意见不能为空');
    if (text.length > 2000) throw new BadRequestException('修改意见过长（上限 2000 字）');

    const m = await this.prisma.monthly.findUnique({ where: { id: monthlyId } });
    if (!m) throw new NotFoundException('月刊不存在');

    const content: any = JSON.parse(JSON.stringify(m.content ?? {}));
    content.pendingNote = text;
    content.pendingNoteAt = new Date().toISOString();
    await this.prisma.monthly.update({
      where: { id: monthlyId },
      data: { content },
    });
    return { ok: true, pendingNote: text };
  }

} // 外壳

// ── 片段三:原 monthly.controller.ts 的 MonthlyController 类里我加的接口 ──
class MonthlyController { // 外壳
  /** 人工修改意见入口。只记录,不改稿——改稿要过 F 门,在产线那边做。 */
  @Post(':id/revision-note')
  revisionNote(@Param('id') id: string, @Body() body: { note?: string }) {
    return this.monthly.submitRevisionNote(id, body?.note ?? '');
  }

} // 外壳

// ── 片段四:原 contracts/heng-backend.openapi.json 的 paths 里我加的一项(JSON 原样) ──
const openapiPaths = { // 外壳
        "/api/v1/monthlies/{id}/revision-note": {
            "post": {
                "operationId": "MonthlyController_revisionNote",
                "parameters": [
                    {
                        "name": "id",
                        "required": true,
                        "in": "path",
                        "schema": {
                            "type": "string"
                        }
                    }
                ],
                "responses": {
                    "201": {
                        "description": ""
                    }
                },
                "tags": [
                    "Monthly"
                ]
            }
        },
}; // 外壳
