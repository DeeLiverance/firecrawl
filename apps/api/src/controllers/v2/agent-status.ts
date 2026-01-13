import { Response } from "express";
import { AgentStatusResponse, RequestWithAuth } from "./types";
import {
  supabaseGetAgentByIdDirect,
  supabaseGetAgentRequestByIdDirect,
} from "../../lib/supabase-jobs";
import { logger as _logger } from "../../lib/logger";
import { getJobFromGCS } from "../../lib/gcs-jobs";

export async function agentStatusController(
  req: RequestWithAuth<{ jobId: string }, AgentStatusResponse, any>,
  res: Response<AgentStatusResponse>,
) {
  const agentRequest = await supabaseGetAgentRequestByIdDirect(
    req.params.jobId,
  );

  if (!agentRequest || agentRequest.team_id !== req.auth.team_id) {
    return res.status(404).json({
      success: false,
      error: "Agent job not found",
    });
  }

  const agent = await supabaseGetAgentByIdDirect(req.params.jobId);

  let data: any = undefined;
  if (agent?.is_successful) {
    data = await getJobFromGCS(agent.id);
  }

  return res.status(200).json({
    success: true,
    status: !agent
      ? "processing"
      : agent.is_successful
        ? "completed"
        : "failed",
    error: agent?.error || undefined,
    data,
    expiresAt: new Date(
      new Date(agent?.created_at ?? agentRequest.created_at).getTime() +
        1000 * 60 * 60 * 24,
    ).toISOString(),
    creditsUsed: agent?.credits_cost,
  });
}
