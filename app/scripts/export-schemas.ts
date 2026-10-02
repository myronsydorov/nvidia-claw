// Dumps every wire-shape zod schema's JSON Schema to stdout as one JSON object,
// keyed by the same model name used in warden/src/warden/models.py.
// Used only by warden/tests/test_contract_zod_sync.py — never imported by the app.
import { z } from "zod";
import * as schemas from "../src/api/schemas.ts";

const modelToSchema: Record<string, z.ZodType> = {
	HealthResponse: schemas.healthResponseSchema,
	Worry: schemas.worrySchema,
	PermissionLine: schemas.permissionLineSchema,
	WatchResult: schemas.watchResultSchema,
	Watcher: schemas.watcherSchema,
	TimelineEvent: schemas.timelineEventSchema,
	WorrySummary: schemas.worrySummarySchema,
	WorryDetail: schemas.worryDetailSchema,
	WorryCreateRequest: schemas.worryCreateRequestSchema,
	OutcomeRequest: schemas.outcomeRequestSchema,
	Peer: schemas.peerSchema,
	PairingStartRequest: schemas.pairingStartRequestSchema,
	PairingStartResponse: schemas.pairingStartResponseSchema,
	PairingStatusResponse: schemas.pairingStatusResponseSchema,
	PairingJoinRequest: schemas.pairingJoinRequestSchema,
	ReassuranceAnswer: schemas.reassuranceAnswerSchema,
	PrivacyReceipt: schemas.privacyReceiptSchema,
	PeopleListItem: schemas.peopleListItemSchema,
	AskPeerRequest: schemas.askPeerRequestSchema,
	AskPeerResponse: schemas.askPeerResponseSchema,
	SharingRule: schemas.sharingRuleSchema,
	QuestionLogEntry: schemas.questionLogEntrySchema,
	SharingRulesResponse: schemas.sharingRulesResponseSchema,
	PushSubscription: schemas.pushSubscriptionSchema,
	LedgerResponse: schemas.ledgerResponseSchema,
	TalkRequest: schemas.talkRequestSchema,
	TalkReply: schemas.talkReplySchema,
	DailyClose: schemas.dailyCloseSchema,
	Event: schemas.eventSchema,
};

const out: Record<string, unknown> = {};
for (const [name, schema] of Object.entries(modelToSchema)) {
	out[name] = z.toJSONSchema(schema);
}

process.stdout.write(JSON.stringify(out));
