// S3: chk: 확장 요소를 bpmn-moddle에 알려 주는 설명 (index.html?moddle=1 일 때만 쓴다)
window.CHK_MODDLE = {
 "name": "Chaeksas",
 "uri": "urn:chaeksas:bpmn:1",
 "prefix": "chk",
 "xml": {
  "tagAlias": "lowerCase"
 },
 "types": [
  {
   "name": "AiTask",
   "superClass": [
    "Element"
   ],
   "properties": [
    {
     "name": "value",
     "type": "String",
     "isBody": true
    }
   ]
  },
  {
   "name": "Approval",
   "superClass": [
    "Element"
   ],
   "properties": [
    {
     "name": "value",
     "type": "String",
     "isBody": true
    }
   ]
  },
  {
   "name": "Call",
   "superClass": [
    "Element"
   ],
   "properties": [
    {
     "name": "value",
     "type": "String",
     "isBody": true
    }
   ]
  },
  {
   "name": "DataOutput",
   "superClass": [
    "Element"
   ],
   "properties": [
    {
     "name": "value",
     "type": "String",
     "isBody": true
    }
   ]
  },
  {
   "name": "Defaults",
   "superClass": [
    "Element"
   ],
   "properties": [
    {
     "name": "value",
     "type": "String",
     "isBody": true
    }
   ]
  },
  {
   "name": "Email",
   "superClass": [
    "Element"
   ],
   "properties": [
    {
     "name": "value",
     "type": "String",
     "isBody": true
    }
   ]
  },
  {
   "name": "Loop",
   "superClass": [
    "Element"
   ],
   "properties": [
    {
     "name": "value",
     "type": "String",
     "isBody": true
    }
   ]
  },
  {
   "name": "Process",
   "superClass": [
    "Element"
   ],
   "properties": [
    {
     "name": "value",
     "type": "String",
     "isBody": true
    }
   ]
  },
  {
   "name": "Receive",
   "superClass": [
    "Element"
   ],
   "properties": [
    {
     "name": "value",
     "type": "String",
     "isBody": true
    }
   ]
  },
  {
   "name": "Rule",
   "superClass": [
    "Element"
   ],
   "properties": [
    {
     "name": "value",
     "type": "String",
     "isBody": true
    }
   ]
  },
  {
   "name": "ServiceCall",
   "superClass": [
    "Element"
   ],
   "properties": [
    {
     "name": "value",
     "type": "String",
     "isBody": true
    }
   ]
  },
  {
   "name": "Task",
   "superClass": [
    "Element"
   ],
   "properties": [
    {
     "name": "value",
     "type": "String",
     "isBody": true
    },
    {
     "name": "type",
     "type": "String",
     "isAttr": true
    },
    {
     "name": "extension",
     "type": "String",
     "isAttr": true
    }
   ]
  },
  {
   "name": "Webhook",
   "superClass": [
    "Element"
   ],
   "properties": [
    {
     "name": "value",
     "type": "String",
     "isBody": true
    }
   ]
  }
 ]
};
