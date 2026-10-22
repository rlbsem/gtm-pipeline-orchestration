@IsTest
private class GTMConnectedGateTest {
    @IsTest static void connectedAtomicReceipt() {
        Id originalUser = UserInfo.getUserId();
        User u = new User(Alias='gtmconn', Email='test@example.invalid', EmailEncodingKey='UTF-8',
            LastName='Synthetic GTM Connected', LanguageLocaleKey='en_US', LocaleSidKey='en_US',
            TimeZoneSidKey='America/Toronto', ProfileId=UserInfo.getProfileId(),
            Username='gtm.connected.'+System.now().getTime()+'.'+Crypto.getRandomInteger()+'@example.invalid');
        insert u;
        insert new PermissionSetAssignment(AssigneeId=u.Id,
            PermissionSetId=[SELECT Id FROM PermissionSet WHERE Name='GTM_Standard_Integration'].Id);
        System.runAs(u) {
            String run='gtm-standard-connected-apex';
            Account a=new Account(Name='SYNTHETIC GTM connected',OwnerId=u.Id,Website='https://account-04.example',
                GTM_Test_Key__c=run+'/account-a',GTM_Test_Active__c=true); insert a;
            Contact c=new Contact(LastName='SYNTHETIC GTM',OwnerId=u.Id,AccountId=a.Id,
                Email='review+'+run+'@account-04.example',GTM_Test_Key__c=run+'/contact-a'); insert c;
            Map<String,Object> p=new Map<String,Object>{'version'=>'gtm-connected-v1','run_id'=>run,
                'action_key'=>'a'.repeat(64),'account_id'=>String.valueOf(a.Id),'contact_id'=>String.valueOf(c.Id),
                'owner_id'=>String.valueOf(u.Id),'notice'=>'Synthetic internal handoff only. No outbound communication.',
                'signal_hash'=>'b'.repeat(64),'model_hash'=>'c'.repeat(64),'review_hash'=>'d'.repeat(64),'question_id'=>'planning',
                'message'=>'Synthetic job-posting evidence: "We are hiring a Network Infrastructure Engineer to support a second regional data center."\n' +
                    'A job posting does not establish budget, purchase intent or timing.\nSuggested outreach for seller review only: Would a conversation about the infrastructure planning described in this posting be useful?'};
            Task t=new Task(WhatId=a.Id,WhoId=c.Id,OwnerId=u.Id,Subject=GTMTaskGate.SUBJECT,Status='Not Started',
                Priority='Normal',IsReminderSet=false,Description=JSON.serialize(p),GTM_Action_Key__c='a'.repeat(64));
            insert t;
            GTM_Task_Receipt__c receipt=[SELECT Payload__c,Payload_Hash__c,Task_Id__c FROM GTM_Task_Receipt__c];
            System.assertEquals(t.Description,receipt.Payload__c);
            System.assertEquals(String.valueOf(t.Id),receipt.Task_Id__c);
            System.assertEquals(EncodingUtil.convertToHex(Crypto.generateDigest('SHA-256',Blob.valueOf(t.Description))),receipt.Payload_Hash__c);
            Task duplicate=t.clone(false,true,false,false);
            System.assertEquals(false,Database.insert(duplicate,false).isSuccess());
            System.assertEquals(1,[SELECT count() FROM Task]);
            c.OwnerId=originalUser; update c;
            p.put('action_key','f'.repeat(64));
            duplicate.GTM_Action_Key__c='f'.repeat(64); duplicate.Description=JSON.serialize(p);
            Database.SaveResult changedOwner=Database.insert(duplicate,false);
            System.assertEquals(false,changedOwner.isSuccess());
            System.assert(changedOwner.getErrors()[0].getMessage().contains('GTM_SCOPE_OR_AUTHORITY_REJECTED'));
            c.OwnerId=u.Id; update c;
            p.put('version','gtm-standard-v1'); p.put('action_key','e'.repeat(64));
            duplicate.GTM_Action_Key__c='e'.repeat(64); duplicate.Description=JSON.serialize(p);
            System.assertEquals(false,Database.insert(duplicate,false).isSuccess());
            System.assertEquals(1,[SELECT count() FROM GTM_Task_Receipt__c]);
        }
    }
    @IsTest static void finiteContentContract() {
        Map<String,Object> p = new Map<String,Object>{'version'=>'gtm-connected-v1','run_id'=>'run',
            'action_key'=>'key','account_id'=>'a','contact_id'=>'c','owner_id'=>'o','notice'=>'notice',
            'signal_hash'=>'a'.repeat(64),'model_hash'=>'b'.repeat(64),'review_hash'=>'c'.repeat(64),
            'question_id'=>'planning',
            'message'=>'Synthetic job-posting evidence: "We are hiring a Network Infrastructure Engineer to support a second regional data center."\n' +
                'A job posting does not establish budget, purchase intent or timing.\nSuggested outreach for seller review only: Would a conversation about the infrastructure planning described in this posting be useful?'};
        System.assertEquals(true,GTMTaskGate.contentValid(p));
        p.put('message','They have approved a million-dollar budget.');
        System.assertEquals(false,GTMTaskGate.contentValid(p));
        p.put('question_id','send_email'); System.assertEquals(false,GTMTaskGate.contentValid(p));
        p.put('question_id','planning'); p.put('model_hash','bad');
        System.assertEquals(false,GTMTaskGate.contentValid(p));
        p.put('version','gtm-standard-v1');
        System.assertEquals(false,GTMTaskGate.contentValid(p));
    }
}
