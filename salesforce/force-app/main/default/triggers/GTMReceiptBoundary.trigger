trigger GTMReceiptBoundary on GTM_Task_Receipt__c (before update, before delete) {
    for (GTM_Task_Receipt__c row : Trigger.old) row.addError('GTM_IMMUTABLE_RECEIPT');
}

