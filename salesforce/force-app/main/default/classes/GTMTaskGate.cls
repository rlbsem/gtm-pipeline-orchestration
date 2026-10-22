public without sharing class GTMTaskGate {
    public static final String SUBJECT = 'SYNTHETIC GTM SDR handoff - no prospect communication';
    public static Boolean contentValid(Map<String,Object> p) {
        if (p.size() == 8 && p.get('version') == 'gtm-standard-v1')
            return p.get('message') == 'Review the synthetic account evidence before any seller action.';
        if (p.size() != 12 || p.get('version') != 'gtm-connected-v1') return false;
        for (String field : new List<String>{'signal_hash','model_hash','review_hash'}) {
            if (!(p.get(field) instanceof String) || !Pattern.matches('[a-f0-9]{64}', (String)p.get(field))) return false;
        }
        String question;
        if (p.get('question_id') == 'planning') question = 'Would a conversation about the infrastructure planning described in this posting be useful?';
        else if (p.get('question_id') == 'ownership') question = 'Who is responsible for the infrastructure planning described in this posting?';
        else return false;
        String expected = 'Synthetic job-posting evidence: "We are hiring a Network Infrastructure Engineer to support a second regional data center."\n' +
            'A job posting does not establish budget, purchase intent or timing.\nSuggested outreach for seller review only: ' + question;
        return p.get('message') == expected;
    }
    public static void validate(List<Task> rows) {
        Boolean writer = FeatureManagement.checkPermission('GTM_Native_Writer');
        Set<Id> accounts = new Set<Id>(), contacts = new Set<Id>();
        List<Task> scoped = new List<Task>();
        for (Task row : rows) {
            if (!writer && row.GTM_Action_Key__c == null) continue;
            scoped.add(row);
            if (row.WhatId != null && row.WhatId.getSObjectType() == Account.SObjectType) accounts.add(row.WhatId);
            if (row.WhoId != null && row.WhoId.getSObjectType() == Contact.SObjectType) contacts.add(row.WhoId);
        }
        if (scoped.isEmpty()) return;
        Map<Id,Account> aa = new Map<Id,Account>([SELECT Id, OwnerId, Website, GTM_Test_Key__c, GTM_Test_Active__c FROM Account WHERE Id IN :accounts FOR UPDATE]);
        Map<Id,Contact> cc = new Map<Id,Contact>([SELECT Id, AccountId, Email, HasOptedOutOfEmail, GTM_Test_Key__c FROM Contact WHERE Id IN :contacts FOR UPDATE]);
        Set<Id> openAccounts = new Set<Id>();
        for (Opportunity opp : [SELECT AccountId FROM Opportunity WHERE AccountId IN :accounts AND IsClosed=false]) openAccounts.add(opp.AccountId);
        for (Task row : scoped) {
            try {
                Map<String,Object> p = (Map<String,Object>)JSON.deserializeUntyped(row.Description);
                String run = (String)p.get('run_id');
                Account a = aa.get(row.WhatId); Contact c = cc.get(row.WhoId);
                Boolean valid = writer && row.Subject == SUBJECT &&
                    row.GTM_Action_Key__c != null && Pattern.matches('[a-f0-9]{64}', row.GTM_Action_Key__c) &&
                    contentValid(p) &&
                    run != null && Pattern.matches('gtm-standard-[a-z0-9-]{8,60}', run) &&
                    p.get('action_key') == row.GTM_Action_Key__c &&
                    p.get('account_id') == String.valueOf(row.WhatId) &&
                    p.get('contact_id') == String.valueOf(row.WhoId) &&
                    p.get('owner_id') == String.valueOf(row.OwnerId) &&
                    p.get('notice') == 'Synthetic internal handoff only. No outbound communication.' &&
                    a != null && c != null && a.GTM_Test_Active__c && a.OwnerId == row.OwnerId &&
                    a.GTM_Test_Key__c == run + '/account-a' && c.GTM_Test_Key__c == run + '/contact-a' &&
                    a.Website == 'https://account-04.example' && c.Email == 'review+' + run + '@account-04.example' &&
                    c.AccountId == a.Id && !c.HasOptedOutOfEmail && !openAccounts.contains(a.Id) &&
                    row.Status == 'Not Started' && row.Priority == 'Normal' && row.IsReminderSet == false;
                if (!valid) row.addError('GTM_SCOPE_OR_AUTHORITY_REJECTED');
            } catch (Exception e) { row.addError('GTM_INVALID_ENVELOPE'); }
        }
    }
}

