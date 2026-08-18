'use strict';

const { Contract } = require('fabric-contract-api');

/**
 * AI-EDGE governance decision ledger.
 *
 * Stores immutable governance decisions (keyed by decision_id) produced by the
 * pipeline's rule engine, giving a tamper-evident, verifiable audit trail across
 * organisations (SDG 16/17). The value stored is the decision object exactly as
 * validated against schemas/governance_decision.schema.json, plus the ledger
 * transaction id.
 */
class GovernanceContract extends Contract {
    /**
     * Record a governance decision. `decisionJson` is the JSON string of a
     * governance_decision object. Returns the ledger transaction id.
     */
    async RecordDecision(ctx, decisionJson) {
        let decision;
        try {
            decision = JSON.parse(decisionJson);
        } catch (err) {
            throw new Error(`invalid decision JSON: ${err.message}`);
        }
        const id = decision.decision_id;
        if (!id) {
            throw new Error('decision is missing decision_id');
        }
        const exists = await this.DecisionExists(ctx, id);
        if (exists) {
            throw new Error(`decision ${id} already exists`);
        }

        const txId = ctx.stub.getTxID();
        decision.ledger_tx_id = txId;
        await ctx.stub.putState(id, Buffer.from(JSON.stringify(decision)));
        return txId;
    }

    /** Return a stored decision by id (JSON string). */
    async GetDecision(ctx, decisionId) {
        const data = await ctx.stub.getState(decisionId);
        if (!data || data.length === 0) {
            throw new Error(`decision ${decisionId} does not exist`);
        }
        return data.toString();
    }

    /** True if a decision id exists. */
    async DecisionExists(ctx, decisionId) {
        const data = await ctx.stub.getState(decisionId);
        return data && data.length > 0;
    }

    /** Return all stored decisions as a JSON array string. */
    async GetAllDecisions(ctx) {
        const results = [];
        const iterator = await ctx.stub.getStateByRange('', '');
        let res = await iterator.next();
        while (!res.done) {
            try {
                results.push(JSON.parse(res.value.value.toString()));
            } catch (err) {
                // skip non-JSON keys
            }
            res = await iterator.next();
        }
        await iterator.close();
        return JSON.stringify(results);
    }

    /** Return the immutable modification history for one decision id. */
    async GetDecisionHistory(ctx, decisionId) {
        const iterator = await ctx.stub.getHistoryForKey(decisionId);
        const history = [];
        let res = await iterator.next();
        while (!res.done) {
            history.push({
                tx_id: res.value.txId,
                timestamp: res.value.timestamp,
                is_delete: res.value.isDelete,
                value: res.value.value ? res.value.value.toString() : null,
            });
            res = await iterator.next();
        }
        await iterator.close();
        return JSON.stringify(history);
    }
}

module.exports = GovernanceContract;
