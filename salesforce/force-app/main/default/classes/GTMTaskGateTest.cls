@IsTest
private class GTMTaskGateTest {
    static final String RUN = 'gtm-standard-apex-test';
    static User writer() {
        User u = new User(Alias='gtmtest', Email='test@example.invalid',
            EmailEncodingKey='UTF-8', LastName='Synthetic GTM', LanguageLocaleKey='en_US',
            LocaleSidKey='en_US', TimeZoneSidKey='America/Toronto', ProfileId=UserInfo.getProfileId(),
            Username='gtm.' + System.now().getTime() + '.' + Crypto.getRandomInteger() + '@example.invalid');
        insert u;
        insert new PermissionSetAssignment(AssigneeId=u.Id,
            PermissionSetId=[SELECT Id FROM PermissionSet WHERE Name='GTM_Standard_Integration'].Id);
        return u;
    }
    static Task payload(Account a, Contact c, String key) {
        Map<String,Object> p = new Map<String,Object>{'version'=>'gtm-standard-v1', 'run_id'=>RUN,
            'action_key'=>key, 'account_id'=>String.valueOf(a.Id), 'contact_id'=>String.valueOf(c.Id),
            'owner_id'=>String.valueOf(a.OwnerId),
            'notice'=>'Synthetic internal handoff only. No outbound communication.',
            'message'=>'Review the synthetic account evidence before any seller action.'};
        return new Task(WhatId=a.Id, WhoId=c.Id, OwnerId=a.OwnerId, Subject=GTMTaskGate.SUBJECT,
            Status='Not Started', Priority='Normal', IsReminderSet=false,
            Description=JSON.serialize(p), GTM_Action_Key__c=key);
    }
    static Account account() {
        Account a = new Account(Name='SYNTHETIC GTM Apex', OwnerId=UserInfo.getUserId(), Website='https://account-04.example',
            GTM_Test_Key__c=RUN+'/account-a', GTM_Test_Active__c=true);
        insert a; return a;
    }
    static Contact contact(Account a) {
        Contact c = new Contact(LastName='SYNTHETIC GTM', AccountId=a.Id,
            Email='review+'+RUN+'@account-04.example', GTM_Test_Key__c=RUN+'/contact-a');
        insert c; return c;
    }
    @IsTest static void atomicReceiptAndImmutableAction() {
        User u=writer();
        System.runAs(u) {
            Account a=account(); Contact c=contact(a);
            Task t=payload(a,c,'a'.repeat(64)); insert t;
            GTM_Task_Receipt__c r=[SELECT Task_Id__c,Payload__c,Payload_Hash__c FROM GTM_Task_Receipt__c];
            System.assertEquals(String.valueOf(t.Id),r.Task_Id__c);
            System.assertEquals(t.Description,r.Payload__c);
            System.assertEquals(EncodingUtil.convertToHex(Crypto.generateDigest('SHA-256',Blob.valueOf(t.Description))),r.Payload_Hash__c);
            Database.SaveResult duplicate=Database.insert(payload(a,c,'a'.repeat(64)),false);
            System.assertEquals(false,duplicate.isSuccess());
            System.assertEquals(1,[SELECT count() FROM Task]);
            t.Description='changed'; System.assertEquals(false,Database.update(t,false).isSuccess());
            System.assertEquals(false,Database.delete(t,false).isSuccess());
            r.Payload__c='changed'; System.assertEquals(false,Database.update(r,false).isSuccess());
            System.assertEquals(false,Database.delete(r,false).isSuccess());
        }
    }
    @IsTest static void authorityAndScopeRejection() {
        User u=writer();
        System.runAs(u) {
            Account a=account(); Contact c=contact(a);
            c.HasOptedOutOfEmail=true; update c;
            System.assertEquals(false,Database.insert(payload(a,c,'b'.repeat(64)),false).isSuccess());
            c.HasOptedOutOfEmail=false; update c;
            Account other=new Account(Name='SYNTHETIC other'); insert other;
            c.AccountId=other.Id; update c;
            System.assertEquals(false,Database.insert(payload(a,c,'c'.repeat(64)),false).isSuccess());
            c.AccountId=a.Id; update c;
            a.GTM_Test_Active__c=false; update a;
            System.assertEquals(false,Database.insert(payload(a,c,'d'.repeat(64)),false).isSuccess());
            a.GTM_Test_Active__c=true; update a;
            String stage=[SELECT MasterLabel FROM OpportunityStage WHERE IsActive=true AND IsClosed=false LIMIT 1].MasterLabel;
            insert new Opportunity(Name='SYNTHETIC open',AccountId=a.Id,CloseDate=Date.today().addDays(30),StageName=stage);
            System.assertEquals(false,Database.insert(payload(a,c,'e'.repeat(64)),false).isSuccess());
            Task unscoped=new Task(Subject='Not permitted');
            System.assertEquals(false,Database.insert(unscoped,false).isSuccess());
            System.assertEquals(0,[SELECT count() FROM Task]);
            System.assertEquals(0,[SELECT count() FROM GTM_Task_Receipt__c]);
        }
    }
    @IsTest static void ordinaryTasksUnaffectedAndForgeryRejected() {
        Account a=account(); Contact c=contact(a);
        Task ordinary=new Task(Subject='ordinary test'); insert ordinary;
        ordinary.Subject='ordinary update'; update ordinary; delete ordinary;
        System.assertEquals(false,Database.insert(payload(a,c,'f'.repeat(64)),false).isSuccess());
    }
}
