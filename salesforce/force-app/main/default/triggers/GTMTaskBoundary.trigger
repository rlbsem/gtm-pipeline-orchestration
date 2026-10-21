trigger GTMTaskBoundary on Task (before insert, before update, before delete, after insert) {
    if (Trigger.isBefore && Trigger.isInsert) GTMTaskGate.validate(Trigger.new);
    if (Trigger.isBefore && !Trigger.isInsert) {
        for (Task oldRow : Trigger.old) {
            Task nextRow = Trigger.isDelete ? null : Trigger.newMap.get(oldRow.Id);
            if (FeatureManagement.checkPermission('GTM_Native_Writer') ||
                (oldRow.GTM_Action_Key__c != null && (nextRow == null ||
                nextRow.GTM_Action_Key__c != oldRow.GTM_Action_Key__c ||
                nextRow.WhoId != oldRow.WhoId || nextRow.WhatId != oldRow.WhatId ||
                nextRow.OwnerId != oldRow.OwnerId || nextRow.Subject != oldRow.Subject ||
                nextRow.Description != oldRow.Description))) oldRow.addError('GTM_IMMUTABLE_ACTION');
        }
    }
    if (Trigger.isAfter && Trigger.isInsert) {
        List<GTM_Task_Receipt__c> receipts = new List<GTM_Task_Receipt__c>();
        for (Task row : Trigger.new) if (row.GTM_Action_Key__c != null)
            receipts.add(new GTM_Task_Receipt__c(Action_Key__c=row.GTM_Action_Key__c,
                Task_Id__c=row.Id, Payload__c=row.Description,
                Payload_Hash__c=EncodingUtil.convertToHex(Crypto.generateDigest('SHA-256', Blob.valueOf(row.Description)))));
        // Unhandled unique-key failure rolls back BOTH receipt and Task in this transaction.
        if (!receipts.isEmpty()) insert receipts;
    }
}

